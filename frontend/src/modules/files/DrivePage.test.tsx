import {
  QueryClient,
  QueryClientProvider,
} from '@tanstack/react-query'
import {
  render,
  screen,
} from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { DirectoryService } from '../../api/generated'
import {
  DirectoryRecipientPicker,
  type DirectoryRecipient,
} from './DrivePage'

vi.mock('../../api/generated', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/generated')>()
  return {
    ...actual,
    DirectoryService: {
      listDirectoryDepartmentsApiV1DirectoryDepartmentsGet: vi.fn(),
      listDirectoryGroupsApiV1DirectoryGroupsGet: vi.fn(),
      listDirectoryUsersApiV1DirectoryUsersGet: vi.fn(),
    },
  }
})

function renderPicker(
  onChange: (value: DirectoryRecipient[]) => void,
  recipients: DirectoryRecipient[] = [],
) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  })
  return render(
    <QueryClientProvider client={client}>
      <DirectoryRecipientPicker onChange={onChange} recipients={recipients} />
    </QueryClientProvider>,
  )
}

describe('DirectoryRecipientPicker', () => {
  beforeEach(() => {
    vi.mocked(
      DirectoryService.listDirectoryUsersApiV1DirectoryUsersGet,
    ).mockResolvedValue({
      items: [{
        display_name: 'Alice',
        id: 'user-1',
        username: 'alice',
      }],
      next_cursor: null,
    })
    vi.mocked(
      DirectoryService.listDirectoryDepartmentsApiV1DirectoryDepartmentsGet,
    ).mockResolvedValue({
      items: [{
        id: 'department-1',
        name: '研发部',
        path: '/总部/研发部',
      }],
      next_cursor: null,
    })
    vi.mocked(
      DirectoryService.listDirectoryGroupsApiV1DirectoryGroupsGet,
    ).mockResolvedValue({
      items: [{
        id: 'group-1',
        name: '产品评审组',
        slug: 'product-reviewers',
      }],
      next_cursor: null,
    })
  })

  it('loads all subject types and selects the active option with the keyboard', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    renderPicker(onChange)

    const input = screen.getByRole('combobox', { name: '接收人' })
    await user.type(input, '研')

    expect(await screen.findByText('Alice')).toBeInTheDocument()
    expect(screen.getByText('研发部')).toBeInTheDocument()
    expect(screen.getByText('产品评审组')).toBeInTheDocument()

    await user.keyboard('{ArrowDown}{Enter}')

    expect(onChange).toHaveBeenCalledWith([
      expect.objectContaining({
        id: 'department-1',
        type: 'department',
      }),
    ])
  })

  it('removes an existing recipient with an accessible button', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    renderPicker(onChange, [{
      description: '用户 · @alice',
      id: 'user-1',
      label: 'Alice',
      type: 'user',
    }])

    await user.click(screen.getByRole('button', { name: '移除 Alice' }))

    expect(onChange).toHaveBeenCalledWith([])
  })
})
