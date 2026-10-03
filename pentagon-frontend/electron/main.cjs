const path = require('node:path')
const { app, BrowserWindow, session, shell } = require('electron')
const { startUiServer } = require('./uiServer.cjs')

const isDev = process.argv.includes('--dev')
const backendUrl = process.env.PENTAGON_API_URL || process.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
const assetsDirectory = path.join(__dirname, '..', 'dist')
let uiServer
let uiOrigin

async function createWindow() {
  const window = new BrowserWindow({
    width: 1390,
    height: 930,
    minWidth: 760,
    minHeight: 620,
    backgroundColor: '#0c0d0f',
    title: 'Pentagon',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })

  let destination
  if (isDev) {
    destination = 'http://127.0.0.1:5173'
  } else {
    const localUi = await startUiServer({ assetsDirectory, backendUrl })
    uiServer = localUi.server
    destination = localUi.origin
  }
  uiOrigin = new URL(destination).origin
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
    try { origin = new URL(details.requestingUrl || webContents.getURL()).origin } catch { /* Deny unknown origins. */ }
    callback(permission === 'media' && origin === uiOrigin)
  })
  await window.loadURL(destination)
}

app.whenReady().then(createWindow).catch((error) => {
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
