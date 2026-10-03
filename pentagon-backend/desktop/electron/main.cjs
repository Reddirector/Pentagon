const path = require('node:path')
const { app, BrowserWindow, session, shell } = require('electron')
const { startUiServer } = require('./uiServer.cjs')

const isDev = process.argv.includes('--dev')
const backendUrl = process.env.PENTAGON_API_URL || 'http://127.0.0.1:8000'
const builtAssets = path.join(__dirname, '..', 'dist')
let uiServer
let uiOrigin

async function servePackagedUi() {
  const localUi = await startUiServer({ assetsDirectory: builtAssets, backendUrl })
  uiServer = localUi.server
  uiOrigin = localUi.origin
  return uiOrigin
}

async function createWindow() {
  const window = new BrowserWindow({
    width: 1360,
    height: 900,
    minWidth: 740,
    minHeight: 620,
    backgroundColor: '#10131a',
    title: 'Pentagon',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })

  const destination = isDev ? 'http://127.0.0.1:5173' : await servePackagedUi()
  uiOrigin = destination
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) void shell.openExternal(url)
    return { action: 'deny' }
  })
  window.webContents.on('will-navigate', (event, url) => {
    if (url.startsWith(uiOrigin)) return
    event.preventDefault()
    if (/^https?:\/\//i.test(url)) void shell.openExternal(url)
  })
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback, details) => {
    let origin = ''
    try { origin = new URL(details.requestingUrl || webContents.getURL()).origin } catch { /* deny unknown origins */ }
    callback(permission === 'media' && origin === uiOrigin)
  })
  await window.loadURL(destination)
}

app.whenReady().then(() => createWindow()).catch((error) => {
  console.error('Pentagon desktop failed to start:', error)
  app.quit()
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) void createWindow()
})

app.on('before-quit', () => uiServer?.close())
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
