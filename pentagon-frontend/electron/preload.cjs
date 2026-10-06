const { contextBridge, ipcRenderer } = require('electron')

// The renderer runs sandboxed with no node access, which is exactly why the
// capability token has to come through here: the backend hands it to this
// process at start-up, and the page asks for it over IPC rather than reading
// it off disk or fetching it over HTTP.
contextBridge.exposeInMainWorld('pentagon', {
  capability: () => ipcRenderer.invoke('pentagon:capability'),
})

// Read synchronously during preload so the page has a stable identity on its
// very first synchronous call. See readOrCreateUserId in main.cjs for why this
// cannot live in localStorage.
contextBridge.exposeInMainWorld('pentagonUserId', ipcRenderer.sendSync('pentagon:user-id'))