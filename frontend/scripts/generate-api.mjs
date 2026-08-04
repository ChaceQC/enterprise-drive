import {
  mkdtemp,
  readdir,
  readFile,
  rm,
  writeFile,
} from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

const frontendRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '..',
)
const committedOutput = path.join(frontendRoot, 'src', 'api', 'generated')
const check = process.argv.includes('--check')

async function listFiles(root, relative = '') {
  const current = path.join(root, relative)
  const entries = await readdir(current, { withFileTypes: true })
  const files = []

  for (const entry of entries) {
    const child = path.join(relative, entry.name)
    if (entry.isDirectory()) {
      files.push(...await listFiles(root, child))
    } else if (entry.isFile()) {
      files.push(child.replaceAll('\\', '/'))
    }
  }

  return files.sort()
}

async function assertDirectoriesEqual(expected, actual) {
  const expectedFiles = await listFiles(expected)
  const actualFiles = await listFiles(actual)

  if (JSON.stringify(expectedFiles) !== JSON.stringify(actualFiles)) {
    throw new Error('Generated API client file list is stale.')
  }

  for (const relative of expectedFiles) {
    const [expectedBytes, actualBytes] = await Promise.all([
      readFile(path.join(expected, relative)),
      readFile(path.join(actual, relative)),
    ])
    if (!expectedBytes.equals(actualBytes)) {
      throw new Error(`Generated API client is stale: ${relative}`)
    }
  }
}

async function generate(output) {
  const codegenCli = path.join(
    frontendRoot,
    'node_modules',
    'openapi-typescript-codegen',
    'bin',
    'index.js',
  )
  const result = spawnSync(
    process.execPath,
    [
      codegenCli,
      '--input',
      path.join(frontendRoot, 'openapi', 'openapi.json'),
      '--output',
      output,
      '--client',
      'fetch',
      '--useOptions',
      '--useUnionTypes',
      '--exportCore',
      'true',
      '--exportServices',
      'true',
      '--exportModels',
      'true',
      '--exportSchemas',
      'false',
    ],
    {
      cwd: frontendRoot,
      encoding: 'utf-8',
      shell: false,
      stdio: 'inherit',
    },
  )

  if (result.error) {
    throw result.error
  }
  if (result.status !== 0) {
    throw new Error(`OpenAPI client generation failed with exit code ${result.status}.`)
  }

  const generatedFiles = await listFiles(output)
  await Promise.all(generatedFiles.map(async (relative) => {
    const generatedPath = path.join(output, relative)
    const contents = await readFile(generatedPath, 'utf-8')
    await writeFile(generatedPath, `${contents.trimEnd()}\n`, 'utf-8')
  }))
}

if (!check) {
  await rm(committedOutput, { force: true, recursive: true })
  await generate(committedOutput)
  console.log(`Generated TypeScript API client in ${committedOutput}`)
} else {
  const temporaryRoot = await mkdtemp(
    path.join(tmpdir(), 'enterprise-drive-openapi-'),
  )
  const temporaryOutput = path.join(temporaryRoot, 'generated')
  try {
    await generate(temporaryOutput)
    await assertDirectoriesEqual(committedOutput, temporaryOutput)
    console.log('Generated TypeScript API client is current.')
  } finally {
    await rm(temporaryRoot, { force: true, recursive: true })
  }
}
