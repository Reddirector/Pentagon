const path = require('node:path')
const { app, BrowserWindow, ipcMain, session, shell } = require('electron')
const { startUiServer } = require('./uiServer.cjs')

const isDev = process.argv.includes('--dev')
const backendUrl = process.env.PENTAGON_API_URL || process.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
const assetsDirectory = path.join(__dirname, '..', 'dist')
// Without an explicit window icon the taskbar falls back to whatever the
// desktop guesses from the app id, which is how the window ended up wearing
// something that was not the Pentagon mark. Vite copies public/ into dist/ and
// the packager ships dist/, so the same file serves both the dev tree and the
// packaged app -- no extra asset to keep in sync.
const iconPath = path.join(__dirname, '..', isDev ? 'public' : 'dist', 'pentagon-logo.png')
let uiServer
let uiOrigin
// The backend issues this on first run and keeps it in a 0600 file. The page
// needs it to call /api/commands, but must never be handed it over HTTP.
let capabilityToken = ''

ipcMain.handle('pentagon:capability', () => capabilityToken)

/**
 * The install's user id, stored on disk rather than in localStorage.
 *
 * localStorage is keyed by origin, and the packaged app serves itself from an
 * ephemeral port chosen at start-up -- so the origin changes every launch. A
 * localStorage id therefore gave the app a brand new user on every start:
 * the command opt-in reset, conversation history was orphaned, and the database
 * filled with throwaway users. The identity belongs to the installation.
 */
function readOrCreateUserId() {
  const fs = require('node:fs')
  const file = path.join(app.getPath('userData'), 'user-id')
  try {
    const existing = fs.readFileSync(file, 'utf8').trim()
    if (existing) return existing
  } catch { /* No file yet: create one below. */ }
  const created = `pentagon-${require('node:crypto').randomUUID()}`
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true })
    // Write to a scratch name and rename into place. A plain write can be torn
    // by a crash or a full disk, leaving a truncated file that reads as empty
    // -- and the next launch would then mint a *new* id, orphaning every
    // conversation and resetting the command opt-in. That is the exact failure
    // this function exists to prevent, so the write has to be all-or-nothing.
    // rename is atomic within a filesystem and carries the 0600 mode across.
    const scratch = `${file}.${process.pid}.tmp`
    fs.writeFileSync(scratch, created, { mode: 0o600 })
    fs.renameSync(scratch, file)
  } catch (error) {
    console.error('Pentagon could not persist its user id:', error.message)
  }
  return created
}

// Synchronous so the renderer can read it during its first synchronous call,
// before any promise plumbing exists in getLocalUserId().
ipcMain.on('pentagon:user-id', (event) => {
  event.returnValue = readOrCreateUserId()
})

function readCapability() {
  const configHome = process.env.XDG_CONFIG_HOME
    || path.join(require('node:os').homedir(), '.config')
  const file = path.join(configHome, 'pentagon', 'capability-token')
  try {
    return require('node:fs').readFileSync(file, 'utf8').trim()
  } catch {
    // No file yet: the backend creates one the first time it is asked. Until
    // then the commands endpoints refuse, which is the safe direction.
    return ''
  }
}

async function createWindow() {
  capabilityToken = readCapability()
  const window = new BrowserWindow({
    width: 1390,
    height: 930,
    minWidth: 760,
    minHeight: 620,
    backgroundColor: '#0c0d0f',
    title: 'Pentagon',
    icon: iconPath,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      // The renderer cannot read files, so the capability token the backend
      // requires arrives over IPC instead.
      preload: path.join(__dirname, 'preload.cjs'),
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
    callback((permission === 'media' || permission === 'geolocation') && origin === uiOrigin)
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
