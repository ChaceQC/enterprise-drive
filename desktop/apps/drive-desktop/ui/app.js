const invoke = window.__TAURI__.core.invoke;
const byId = (id) => document.getElementById(id);

function formValue(form, name) {
  return new FormData(form).get(name)?.toString().trim() ?? "";
}

function notify(message) {
  const toast = byId("toast");
  toast.textContent = message;
  toast.classList.add("visible");
  window.setTimeout(() => toast.classList.remove("visible"), 3200);
}

async function execute(action) {
  try {
    return await action();
  } catch (error) {
    notify(String(error));
    throw error;
  }
}

function renderRecords(container, records, columns) {
  if (!records.length) {
    container.className = "list empty";
    container.textContent = "没有可显示的数据";
    return;
  }
  container.className = "list";
  container.replaceChildren(
    ...records.map((record) => {
      const row = document.createElement("div");
      row.className = "list-item";
      for (const column of columns) {
        const cell = document.createElement(column.code ? "code" : "span");
        cell.textContent = column.value(record);
        row.append(cell);
      }
      return row;
    }),
  );
}

async function refreshTransfers() {
  const records = await execute(() => invoke("list_transfers"));
  const container = byId("transfers");
  if (!records.length) {
    container.className = "list empty";
    container.textContent = "尚无传输任务";
    return;
  }
  container.className = "list";
  container.replaceChildren(
    ...records.map((task) => {
      const row = document.createElement("div");
      row.className = "list-item";
      const label = document.createElement("strong");
      label.textContent = `${task.direction} · ${task.status}`;
      const progress = document.createElement("code");
      progress.textContent = `${task.transferred_bytes}/${task.size_bytes} · ${task.local_path}`;
      const actions = document.createElement("div");
      actions.className = "transfer-actions";
      for (const [labelText, command] of [
        ["暂停", "pause_transfer"],
        ["继续", "resume_transfer"],
        ["取消", "cancel_transfer"],
      ]) {
        const button = document.createElement("button");
        button.className = "quiet";
        button.textContent = labelText;
        button.addEventListener("click", async () => {
          await execute(() =>
            invoke(command, { request: { taskId: task.id } }),
          );
          await refreshTransfers();
        });
        actions.append(button);
      }
      row.append(label, progress, actions);
      return row;
    }),
  );
}

byId("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const response = await execute(() =>
    invoke("login", {
      request: {
        tenantSlug: formValue(form, "tenantSlug"),
        username: formValue(form, "username"),
        password: formValue(form, "password"),
        deviceName: formValue(form, "deviceName"),
      },
    }),
  );
  notify(`设备 ${response.device.name} 已登录`);
});

byId("restore-session").addEventListener("click", async () => {
  const restored = await execute(() => invoke("restore_session"));
  notify(restored ? "已从系统凭据库恢复设备会话" : "没有可恢复的设备会话");
});

byId("sign-out").addEventListener("click", async () => {
  await execute(() => invoke("sign_out"));
  notify("本机设备凭据已清除");
});

byId("load-spaces").addEventListener("click", async () => {
  const response = await execute(() => invoke("list_spaces"));
  renderRecords(byId("spaces"), response.items, [
    { value: (item) => item.name },
    { value: (item) => item.id, code: true },
    { value: (item) => item.space_type },
  ]);
});

byId("browse-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const parentId = formValue(form, "parentId");
  const response = await execute(() =>
    invoke("list_files", {
      request: {
        spaceId: formValue(form, "spaceId"),
        parentId: parentId || null,
      },
    }),
  );
  renderRecords(byId("files"), response.items, [
    { value: (item) => item.name },
    { value: (item) => item.id, code: true },
    { value: (item) => item.node_type },
  ]);
});

byId("sync-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const response = await execute(() =>
    invoke("configure_sync_root", {
      request: {
        spaceId: formValue(form, "spaceId"),
        rootNodeId: formValue(form, "rootNodeId"),
        localPath: formValue(form, "localPath"),
      },
    }),
  );
  byId("sync-result").textContent =
    `快照 ${response.snapshot_nodes} 项，增量 ${response.applied_changes} 项，` +
    `共 ${response.pages} 页`;
});

byId("pull-sync").addEventListener("click", async () => {
  const form = byId("sync-form");
  const response = await execute(() =>
    invoke("pull_sync_changes", {
      request: { rootNodeId: formValue(form, "rootNodeId") },
    }),
  );
  byId("sync-result").textContent =
    `本次应用 ${response.applied_changes} 项；has_more=${response.has_more}`;
});

byId("offline-list").addEventListener("click", async () => {
  const form = byId("sync-form");
  const records = await execute(() =>
    invoke("list_offline_files", {
      request: {
        spaceId: formValue(form, "spaceId"),
        parentId: formValue(form, "rootNodeId"),
      },
    }),
  );
  byId("sync-result").textContent = records
    .map((item) => `${item.node_type}: ${item.name ?? item.node_id}`)
    .join("\n");
});

byId("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  await execute(() =>
    invoke("start_upload", {
      request: {
        localPath: formValue(form, "localPath"),
        spaceId: formValue(form, "spaceId"),
        parentId: formValue(form, "parentId"),
      },
    }),
  );
  await refreshTransfers();
});

byId("download-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  await execute(() =>
    invoke("start_download", {
      request: {
        nodeId: formValue(form, "nodeId"),
        destination: formValue(form, "destination"),
      },
    }),
  );
  await refreshTransfers();
});

byId("refresh-transfers").addEventListener("click", refreshTransfers);

byId("export-diagnostics").addEventListener("click", async () => {
  const path = await execute(() => invoke("export_diagnostics"));
  notify(`诊断文件已导出：${path}`);
});

execute(async () => {
  byId("version").textContent = `v${await invoke("app_version")}`;
  await refreshTransfers();
});
