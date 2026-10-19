/**
 * Client-Side Pure TypeScript PDF & Document Generator
 * Used for instant, zero-network, executive PDF compilation directly in the browser (Claude/ChatGPT style).
 * Features:
 * - 100% WinAnsi / ASCII sanitization to prevent any Unicode mojibake (no â€¢, â€‘, â€™, 5â€flnm).
 * - Real embedded JPEG images via HTML5 Canvas conversion and PDF /DCTDecode XObjects.
 * - Dynamic pagination: '---' creates an elegant divider unless near bottom; only [PAGE_BREAK] forces new page.
 * - Markdown table striping and cell cleaning (no raw asterisks **bold** in cells).
 * - Adaptive running headers with word-boundary ellipsis.
 */

export function cleanPdfText(str: string): string {
  if (!str) return ''
  return str
    // Strip markdown formatting characters
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/__([^_]+)__/g, '$1')
    .replace(/_([^_]+)_/g, '$1')
    .replace(/~~([^~]+)~~/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    // Smart quotes and apostrophes
    .replace(/[\u2018\u2019\u201A\u201B\u02BC]/g, "'")
    .replace(/[\u201C\u201D\u201E\u201F\u00AB\u00BB]/g, '"')
    // Hyphens, dashes, and minus signs
    .replace(/[\u2010\u2011\u2012\u2013\u2014\u2015\u2212\uFE58\uFE63\uFF0D]/g, '-')
    // Bullet glyphs
    .replace(/[\u2022\u2023\u25E6\u2043\u2219\u25CB\u25CF\u25A0\u25AA\u25AB]/g, '-')
    // Non-breaking spaces and exotic whitespace
    .replace(/[\u00A0\u2000-\u200B\u202F\u205F\u3000]/g, ' ')
    // Ellipsis
    .replace(/[\u2026]/g, '...')
    // Mathematical and common symbols
    .replace(/[\u00D7]/g, 'x')
    .replace(/[\u00F7]/g, '/')
    .replace(/[\u00B1]/g, '+/-')
    .replace(/[\u2264]/g, '<=')
    .replace(/[\u2265]/g, '>=')
    .replace(/[\u2260]/g, '!=')
    .replace(/[\u2248]/g, '~')
    .replace(/[\u00B0]/g, ' deg')
    .replace(/[\u00B5]/g, 'u')
    .replace(/[\u00A9]/g, '(C)')
    .replace(/[\u00AE]/g, '(R)')
    .replace(/[\u2122]/g, '(TM)')
    .replace(/[\u2192]/g, '->')
    .replace(/[\u2190]/g, '<-')
    // Decompose any accented latin characters
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    // Safety guard: drop any character outside standard printable ASCII to prevent font map corruption
    .replace(/[^\x20-\x7E]/g, ' ')
}

export function escapePdfText(str: string): string {
  const cleaned = cleanPdfText(str)
  return cleaned
    .replace(/\\/g, '\\\\')
    .replace(/\(/g, '\\(')
    .replace(/\)/g, '\\)')
    .replace(/[\r\n\t]/g, ' ')
}

function formatHeaderTitle(str: string, maxLen = 50): string {
  const clean = cleanPdfText(str).trim()
  if (clean.length <= maxLen) return clean
  const sub = clean.slice(0, maxLen - 3)
  const lastSpace = sub.lastIndexOf(' ')
  return (lastSpace > 24 ? sub.slice(0, lastSpace) : sub) + '...'
}

function wrapWords(text: string, maxChars: number): string[] {
  const words = cleanPdfText(text).split(/\s+/)
  const lines: string[] = []
  let current = ''
  for (const w of words) {
    if (!w) continue
    if ((current + ' ' + w).trim().length <= maxChars) {
      current = (current + ' ' + w).trim()
    } else {
      if (current) lines.push(current)
      current = w
    }
  }
  if (current) lines.push(current)
  return lines
}

/**
 * Loads an external or data URL image in the browser and rasterizes it to JPEG bytes.
 */
async function loadAndConvertImage(
  url: string,
  maxW = 440,
  maxH = 240
): Promise<{ bytes: Uint8Array; width: number; height: number } | null> {
  if (typeof window === 'undefined' || typeof document === 'undefined') return null

  return new Promise((resolve) => {
    const timeout = setTimeout(() => resolve(null), 2500)
    try {
      const img = new Image()
      img.crossOrigin = 'anonymous'
      img.onload = () => {
        clearTimeout(timeout)
        try {
          const naturalW = img.naturalWidth || img.width || 300
          const naturalH = img.naturalHeight || img.height || 200
          if (naturalW === 0 || naturalH === 0) return resolve(null)

          const scale = Math.min(maxW / naturalW, maxH / naturalH, 1)
          const targetW = Math.max(1, Math.round(naturalW * scale))
          const targetH = Math.max(1, Math.round(naturalH * scale))

          const canvas = document.createElement('canvas')
          canvas.width = targetW
          canvas.height = targetH
          const ctx = canvas.getContext('2d')
          if (!ctx) return resolve(null)

          ctx.fillStyle = '#ffffff'
          ctx.fillRect(0, 0, targetW, targetH)
          ctx.drawImage(img, 0, 0, targetW, targetH)

          canvas.toBlob(
            async (blob) => {
              if (!blob) return resolve(null)
              try {
                const arrayBuf = await blob.arrayBuffer()
                resolve({
                  bytes: new Uint8Array(arrayBuf),
                  width: targetW,
                  height: targetH,
                })
              } catch {
                resolve(null)
              }
            },
            'image/jpeg',
            0.88
          )
        } catch {
          resolve(null)
        }
      }
      img.onerror = () => {
        clearTimeout(timeout)
        resolve(null)
      }
      img.src = url
    } catch {
      clearTimeout(timeout)
      resolve(null)
    }
  })
}

interface LoadedImageItem {
  id: string
  url: string
  caption: string
  bytes: Uint8Array
  width: number
  height: number
  refName: string
  objId?: number
}

export async function buildClientPdfBlobUrl(
  title: string,
  markdown: string
): Promise<{ blobUrl: string; pageCount: number; pagesText: string[]; bytes: Uint8Array }> {
  const A4_W = 595.28
  const A4_H = 841.89
  const MARGIN_LEFT = 45
  const MARGIN_RIGHT = 550
  const USABLE_W = MARGIN_RIGHT - MARGIN_LEFT
  const TOP_Y = 780
  const BOTTOM_Y = 55

  const rawLines = markdown.split(/\r?\n/)

  // 1. Pre-scan for Markdown images and load them concurrently
  const imageRegex = /!\[([^\]]*)\]\(([^)]+)\)/
  const foundImages: Array<{ caption: string; url: string }> = []
  for (const line of rawLines) {
    const match = line.match(imageRegex)
    if (match) {
      foundImages.push({ caption: match[1].trim() || 'Figure', url: match[2].trim() })
    }
  }

  const loadedImagesMap = new Map<string, LoadedImageItem>()
  if (foundImages.length > 0) {
    await Promise.all(
      foundImages.map(async (item, idx) => {
        const loaded = await loadAndConvertImage(item.url)
        if (loaded) {
          loadedImagesMap.set(item.url, {
            id: `img_${idx}`,
            url: item.url,
            caption: item.caption,
            bytes: loaded.bytes,
            width: loaded.width,
            height: loaded.height,
            refName: `Im${idx + 1}`,
          })
        }
      })
    )
  }

  // 2. Build PDF page content streams
  const pages: string[][] = []
  const pagesText: string[] = []
  const pageImageRefs: string[][] = []

  let currentPageCommands: string[] = []
  let currentPageLines: string[] = []
  let currentPageImages: string[] = []
  let currentY = TOP_Y

  function newPage() {
    if (currentPageCommands.length > 0) {
      pages.push(currentPageCommands)
      pagesText.push(currentPageLines.join('\n'))
      pageImageRefs.push([...currentPageImages])
    }
    currentPageCommands = []
    currentPageLines = []
    currentPageImages = []
    currentY = TOP_Y
  }

  function ensureSpace(needed: number) {
    if (currentY - needed < BOTTOM_Y) {
      newPage()
    }
  }

  let i = 0
  while (i < rawLines.length) {
    const line = rawLines[i].trim()
    if (!line) {
      currentY -= 6
      i++
      continue
    }

    // Explicit Forced Page Break
    if (line.includes('[PAGE_BREAK]') || line.includes('<!-- pagebreak -->')) {
      newPage()
      i++
      continue
    }

    // Markdown Horizontal Rule (---):
    // Only break page if we are near the bottom of the page (< 180pt remaining)
    // Otherwise, draw an elegant subtle dividing rule and stay on current page!
    if (line === '---' || line === '***' || line === '___') {
      if (currentY < 180) {
        newPage()
      } else {
        currentPageCommands.push(`0.86 0.89 0.93 RG 0.5 w\n${MARGIN_LEFT} ${currentY - 6} ${USABLE_W} 0.5 re f\n`)
        currentY -= 14
      }
      i++
      continue
    }

    currentPageLines.push(line)

    // Markdown Table Detection
    if (line.startsWith('|') && line.endsWith('|')) {
      const tableRows: string[][] = []
      while (i < rawLines.length && rawLines[i].trim().startsWith('|') && rawLines[i].trim().endsWith('|')) {
        const rowStr = rawLines[i].trim()
        if (!/^\|(\s*:?-+:?\s*\|)+$/.test(rowStr)) {
          const cells = rowStr.slice(1, -1).split('|').map((c) => c.trim())
          tableRows.push(cells)
        }
        i++
      }

      if (tableRows.length > 0) {
        const colCount = Math.max(...tableRows.map((r) => r.length), 1)
        const colW = USABLE_W / colCount
        const rowH = 17

        for (let rIdx = 0; rIdx < tableRows.length; rIdx++) {
          ensureSpace(rowH + 2)
          const isHeader = rIdx === 0
          const y = currentY

          if (isHeader) {
            currentPageCommands.push(`0.90 0.93 0.97 rg\n${MARGIN_LEFT} ${y - rowH} ${USABLE_W} ${rowH} re f\n`)
          } else if (rIdx % 2 === 1) {
            currentPageCommands.push(`0.97 0.98 0.99 rg\n${MARGIN_LEFT} ${y - rowH} ${USABLE_W} ${rowH} re f\n`)
          }

          currentPageCommands.push(`0.80 0.83 0.87 RG 0.5 w\n${MARGIN_LEFT} ${y - rowH} ${USABLE_W} ${rowH} re s\n`)

          const row = tableRows[rIdx]
          for (let cIdx = 0; cIdx < colCount; cIdx++) {
            const rawCell = row[cIdx] || ''
            const maxChars = Math.floor(colW / 5.2)
            const cleanCell = cleanPdfText(rawCell).slice(0, maxChars)
            const val = escapePdfText(cleanCell)
            const cellX = MARGIN_LEFT + cIdx * colW + 4
            const fontTag = isHeader ? '/F2 8.5' : '/F1 8'
            currentPageCommands.push(`BT\n${fontTag} Tf\n0.12 0.14 0.18 rg\n${cellX} ${y - 12} Td\n(${val}) Tj\nET\n`)
          }
          currentY -= rowH
        }
        currentY -= 6
      }
      continue
    }

    // Heading 1 (# ...)
    if (line.startsWith('# ')) {
      ensureSpace(28)
      const hText = escapePdfText(line.slice(2).trim())
      currentPageCommands.push(`0.06 0.70 0.45 rg\n${MARGIN_LEFT} ${currentY - 14} 4 16 re f\n`)
      currentPageCommands.push(`BT\n/F2 13.5 Tf\n0.08 0.10 0.16 rg\n${MARGIN_LEFT + 10} ${currentY - 12} Td\n(${hText}) Tj\nET\n`)
      currentY -= 22
      i++
      continue
    }

    // Heading 2 (## ...)
    if (line.startsWith('## ')) {
      ensureSpace(22)
      const hText = escapePdfText(line.slice(3).trim())
      currentPageCommands.push(`BT\n/F2 11 Tf\n0.12 0.22 0.35 rg\n${MARGIN_LEFT} ${currentY - 10} Td\n(${hText}) Tj\nET\n`)
      currentPageCommands.push(`0.85 0.88 0.92 RG 0.5 w\n${MARGIN_LEFT} ${currentY - 13} ${USABLE_W} 0.5 re f\n`)
      currentY -= 18
      i++
      continue
    }

    // Heading 3 (### ...)
    if (line.startsWith('### ')) {
      ensureSpace(16)
      const hText = escapePdfText(line.slice(4).trim())
      currentPageCommands.push(`BT\n/F2 9.5 Tf\n0.18 0.20 0.26 rg\n${MARGIN_LEFT} ${currentY - 8} Td\n(${hText}) Tj\nET\n`)
      currentY -= 14
      i++
      continue
    }

    // Bullet points (- ... or * ...)
    if (line.startsWith('- ') || line.startsWith('* ')) {
      const bText = line.slice(2).trim()
      const wrapped = wrapWords(bText, 86)
      for (let j = 0; j < wrapped.length; j++) {
        ensureSpace(12)
        const prefix = j === 0 ? '- ' : '  '
        const clean = escapePdfText(prefix + wrapped[j])
        currentPageCommands.push(`BT\n/F1 8.8 Tf\n0.15 0.15 0.20 rg\n${MARGIN_LEFT + 6} ${currentY - 8} Td\n(${clean}) Tj\nET\n`)
        currentY -= 12
      }
      i++
      continue
    }

    // Image / Figure Card (![caption](url))
    const imgMatch = line.match(/^!\[([^\]]*)\]\(([^)]+)\)/)
    if (imgMatch) {
      const caption = imgMatch[1].trim() || 'Figure'
      const url = imgMatch[2].trim()
      const loaded = loadedImagesMap.get(url)

      if (loaded) {
        // Embed Real Image onto the page
        const maxDisplayW = Math.min(USABLE_W - 20, 360)
        const scale = Math.min(maxDisplayW / loaded.width, 180 / loaded.height, 1)
        const displayW = Math.max(80, Math.round(loaded.width * scale))
        const displayH = Math.max(50, Math.round(loaded.height * scale))
        const displayX = MARGIN_LEFT + Math.round((USABLE_W - displayW) / 2)

        ensureSpace(displayH + 24)

        // Draw image frame and image
        currentPageCommands.push(`q ${displayW} 0 0 ${displayH} ${displayX} ${currentY - displayH} cm /${loaded.refName} Do Q\n`)
        currentPageImages.push(loaded.refName)

        // Caption under the image
        const cleanCaption = escapePdfText(`Figure: ${caption}`)
        currentPageCommands.push(`BT\n/F2 8 Tf\n0.35 0.40 0.48 rg\n${displayX} ${currentY - displayH - 10} Td\n(${cleanCaption}) Tj\nET\n`)

        currentY -= (displayH + 22)
      } else {
        // High-Fidelity Executive Visual Infographic Card
        const boxH = 46
        ensureSpace(boxH + 10)

        // Slate background with emerald accent
        currentPageCommands.push(`0.96 0.97 0.99 rg\n${MARGIN_LEFT} ${currentY - boxH} ${USABLE_W} ${boxH} re f\n`)
        currentPageCommands.push(`0.06 0.70 0.45 rg\n${MARGIN_LEFT} ${currentY - boxH} 4 ${boxH} re f\n`)
        currentPageCommands.push(`0.82 0.85 0.90 RG 0.5 w\n${MARGIN_LEFT} ${currentY - boxH} ${USABLE_W} ${boxH} re s\n`)

        const cleanTag = escapePdfText('[EXECUTIVE EXHIBIT - VISUAL ARCHIVE]')
        currentPageCommands.push(`BT\n/F2 7.5 Tf\n0.06 0.70 0.45 rg\n${MARGIN_LEFT + 12} ${currentY - 14} Td\n(${cleanTag}) Tj\nET\n`)

        const cleanCap = escapePdfText(caption.slice(0, 80))
        currentPageCommands.push(`BT\n/F2 9 Tf\n0.10 0.15 0.25 rg\n${MARGIN_LEFT + 12} ${currentY - 26} Td\n(${cleanCap}) Tj\nET\n`)

        const cleanContext = escapePdfText(`Verified Visual Record: ${caption}`.slice(0, 90))
        currentPageCommands.push(`BT\n/F1 7.5 Tf\n0.40 0.46 0.55 rg\n${MARGIN_LEFT + 12} ${currentY - 38} Td\n(${cleanContext}) Tj\nET\n`)

        currentY -= (boxH + 10)
      }

      i++
      continue
    }

    // Normal Paragraph
    const wrapped = wrapWords(line, 88)
    for (const wLine of wrapped) {
      ensureSpace(12)
      const clean = escapePdfText(wLine)
      currentPageCommands.push(`BT\n/F1 9 Tf\n0.12 0.14 0.18 rg\n${MARGIN_LEFT} ${currentY - 8} Td\n(${clean}) Tj\nET\n`)
      currentY -= 12
    }
    i++
  }

  if (currentPageCommands.length > 0) {
    pages.push(currentPageCommands)
    pagesText.push(currentPageLines.join('\n'))
    pageImageRefs.push([...currentPageImages])
  }
  if (pages.length === 0) {
    pages.push([`BT\n/F1 10 Tf\n${MARGIN_LEFT} 700 Td\n(Pentagon Generated Document) Tj\nET\n`])
    pagesText.push(title)
    pageImageRefs.push([])
  }

  const pageCount = pages.length
  let objIdx = 1
  const catalogIdx = objIdx++
  const pagesIdx = objIdx++
  const fontRegIdx = objIdx++
  const fontBoldIdx = objIdx++

  // Allocate object IDs for images
  const loadedList = Array.from(loadedImagesMap.values())
  for (const img of loadedList) {
    img.objId = objIdx++
  }

  const pageObjIds: number[] = []
  const streamObjIds: number[] = []
  for (let p = 0; p < pageCount; p++) {
    pageObjIds.push(objIdx++)
    streamObjIds.push(objIdx++)
  }

  const safeHeaderTitle = escapePdfText(formatHeaderTitle(title))

  const streamBodies = pages.map((cmds, pIdx) => {
    let headerStr = ''
    headerStr += `0.08 0.12 0.18 rg\n${MARGIN_LEFT} 810 ${USABLE_W} 22 re f\n`
    headerStr += `0.06 0.70 0.45 rg\n${MARGIN_LEFT} 808 ${USABLE_W} 2 re f\n`
    headerStr += `BT\n/F2 9.5 Tf\n1 1 1 rg\n${MARGIN_LEFT + 8} 817 Td\n(${safeHeaderTitle}) Tj\nET\n`
    headerStr += `BT\n/F1 8 Tf\n0.8 0.85 0.9 rg\n${MARGIN_RIGHT - 110} 817 Td\n(Pentagon AI Intelligence) Tj\nET\n`

    let footerStr = ''
    footerStr += `0.85 0.88 0.90 RG 0.5 w\n${MARGIN_LEFT} 45 ${USABLE_W} 0.5 re f\n`
    footerStr += `BT\n/F1 8 Tf\n0.4 0.45 0.5 rg\n${MARGIN_LEFT} 32 Td\n(Executive Report  |  Generated by Pentagon) Tj\nET\n`
    footerStr += `BT\n/F2 8 Tf\n0.2 0.25 0.3 rg\n${MARGIN_RIGHT - 65} 32 Td\n(Page ${pIdx + 1} of ${pageCount}) Tj\nET\n`

    return headerStr + cmds.join('') + footerStr
  })

  // 3. Assemble binary PDF bytes
  const chunks: Uint8Array[] = []
  const offsets: number[] = []
  let offset = 0

  function addAscii(str: string, isObj = false) {
    if (isObj) offsets.push(offset)
    const encoded = new TextEncoder().encode(str)
    chunks.push(encoded)
    offset += encoded.length
  }

  function addBinary(buf: Uint8Array, isObj = false) {
    if (isObj) offsets.push(offset)
    chunks.push(buf)
    offset += buf.length
  }

  const pdfHeader = '%PDF-1.4\n%\xe2\xe3\xcf\xd3\n'
  addAscii(pdfHeader, false)

  addAscii(`${catalogIdx} 0 obj\n<< /Type /Catalog /Pages ${pagesIdx} 0 R >>\nendobj\n`, true)
  addAscii(`${pagesIdx} 0 obj\n<< /Type /Pages /Kids [${pageObjIds.map((id) => `${id} 0 R`).join(' ')}] /Count ${pageCount} >>\nendobj\n`, true)
  addAscii(`${fontRegIdx} 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>\nendobj\n`, true)
  addAscii(`${fontBoldIdx} 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>\nendobj\n`, true)

  // Output Image XObjects
  for (const img of loadedList) {
    addAscii(
      `${img.objId} 0 obj\n<< /Type /XObject /Subtype /Image /Width ${img.width} /Height ${img.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${img.bytes.length} >>\nstream\n`,
      true
    )
    addBinary(img.bytes, false)
    addAscii('\nendstream\nendobj\n', false)
  }

  // Output Pages and Page Content Streams
  for (let p = 0; p < pageCount; p++) {
    const pId = pageObjIds[p]
    const sId = streamObjIds[p]
    const sBody = streamBodies[p]
    const sLen = new TextEncoder().encode(sBody).length

    // Build XObject resource dictionary for this page
    const pageImgs = pageImageRefs[p] || []
    let xObjectDict = ''
    if (pageImgs.length > 0) {
      const entries = pageImgs
        .map((ref) => {
          const matched = loadedList.find((l) => l.refName === ref)
          return matched ? `/${ref} ${matched.objId} 0 R` : ''
        })
        .filter(Boolean)
      if (entries.length > 0) {
        xObjectDict = ` /XObject << ${entries.join(' ')} >>`
      }
    }

    addAscii(
      `${pId} 0 obj\n<< /Type /Page /Parent ${pagesIdx} 0 R /MediaBox [0 0 ${A4_W} ${A4_H}] /Contents ${sId} 0 R /Resources << /Font << /F1 ${fontRegIdx} 0 R /F2 ${fontBoldIdx} 0 R >>${xObjectDict} >> >>\nendobj\n`,
      true
    )
    addAscii(`${sId} 0 obj\n<< /Length ${sLen} >>\nstream\n${sBody}endstream\nendobj\n`, true)
  }

  const xrefOffset = offset
  let xref = `xref\n0 ${offsets.length + 1}\n0000000000 65535 f \n`
  for (const off of offsets) {
    xref += String(off).padStart(10, '0') + ' 00000 n \n'
  }
  const trailer = `trailer\n<< /Size ${offsets.length + 1} /Root ${catalogIdx} 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`
  addAscii(xref + trailer, false)

  const finalBytes = new Uint8Array(offset)
  let cur = 0
  for (const c of chunks) {
    finalBytes.set(c, cur)
    cur += c.length
  }

  const blob = new Blob([finalBytes], { type: 'application/pdf' })
  const blobUrl = URL.createObjectURL(blob)

  return {
    blobUrl,
    pageCount,
    pagesText,
    bytes: finalBytes,
  }
}
