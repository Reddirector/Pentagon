const http = require('node:http')
const path = require('node:path')
const express = require('express')
const { createProxyMiddleware } = require('http-proxy-middleware')

async function startUiServer({ assetsDirectory, backendUrl }) {
  const serverApp = express()
  serverApp.use(createProxyMiddleware({
    pathFilter: '/api',
    target: backendUrl,
    changeOrigin: true,
    timeout: 0,
    proxyTimeout: 0,
    on: {
      error(error, _request, response) {
        console.error('Pentagon API proxy failed:', error.message)
        if (!response.headersSent) {
          response.writeHead(502, { 'Content-Type': 'application/json' })
          response.end(JSON.stringify({ detail: 'Could not reach the Pentagon Python backend.' }))
        }
      },
    },
  }))
  serverApp.use(express.static(assetsDirectory))
  serverApp.use((_request, response) => response.sendFile(path.join(assetsDirectory, 'index.html')))

  const server = http.createServer(serverApp)
  await new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', resolve)
  })
  const address = server.address()
  if (!address || typeof address === 'string') throw new Error('Could not start the local UI server.')
  return { server, origin: `http://127.0.0.1:${address.port}` }
}

module.exports = { startUiServer }
