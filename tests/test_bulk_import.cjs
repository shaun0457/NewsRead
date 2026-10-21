const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = file => fs.readFileSync(path.join(__dirname, "../easyread/web/js/", file), "utf8");

test("pickFolder uses desktop picker when in Electron", async () => {
  const PR = {};
  const context = {
    window: {
      PR,
      easyreadDesktop: {
        pickFolder: async () => "/selected/desktop/folder",
      },
    },
  };
  vm.runInNewContext(source("common/pick-folder.js"), context);

  assert.equal(typeof PR.pickFolder, "function");
  const result = await PR.pickFolder({ title: "选择文件夹" });
  assert.equal(result, "/selected/desktop/folder");
});

test("pickFolder calls backend /api/library/pick-folder in browser mode", async () => {
  const calls = [];
  const PR = {
    api: async (url, opts) => {
      calls.push({ url, opts });
      if (url === "/api/library/pick-folder") {
        return { supported: true, path: "/selected/browser/folder" };
      }
      return {};
    },
    t: s => s,
  };
  const context = {
    window: { PR },
  };
  vm.runInNewContext(source("common/pick-folder.js"), context);

  const result = await PR.pickFolder({ title: "选择文件夹" });
  assert.equal(result, "/selected/browser/folder");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/library/pick-folder");
  assert.equal(calls[0].opts.body.title, "选择文件夹");
});

test("pickFolder falls back to promptText if system picker not supported", async () => {
  let promptArgs = null;
  const PR = {
    api: async () => ({ supported: false }),
    promptText: async (args) => {
      promptArgs = args;
      return "/manually/entered/folder";
    },
    t: s => s,
  };
  const context = {
    window: { PR },
  };
  vm.runInNewContext(source("common/pick-folder.js"), context);

  const result = await PR.pickFolder({ title: "输入文件夹" });
  assert.equal(result, "/manually/entered/folder");
  assert.equal(promptArgs.title, "输入文件夹");
});

test("openFolderImport launches folder pick and scans selected directory", async () => {
  const dlg = {
    classList: {
      add: () => {},
      remove: () => {},
      contains: () => false,
    },
    querySelector: () => ({ innerHTML: "" }),
    addEventListener: () => {},
  };
  const apiCalls = [];
  const PR = {
    $: (sel) => sel === "#bulkDlg" ? dlg : { addEventListener: () => {} },
    esc: s => s,
    t: s => s,
    pickFolder: async () => "/user/papers/folder",
    api: async (url, opts) => {
      apiCalls.push({ url, opts });
      if (url === "/api/migrate/status") return { state: "idle" };
      if (url === "/api/migrate/scan") return { path: "/user/papers/folder", with_pdf: 12, collections: 2 };
      return {};
    },
    lib: { useServerSide: () => {}, load: () => {} },
  };

  const context = {
    window: { PR },
    document: { addEventListener: () => {} },
    setTimeout: (fn) => fn(),
    clearTimeout: () => {},
  };
  vm.runInNewContext(source("library/bulk-import.js"), context);

  assert.equal(typeof PR.openFolderImport, "function");
  await PR.openFolderImport();

  assert.ok(apiCalls.some(c => c.url === "/api/migrate/scan" && c.opts.body.path === "/user/papers/folder"));
});
