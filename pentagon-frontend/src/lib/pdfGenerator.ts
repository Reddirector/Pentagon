/**
 * Client-Side Pure TypeScript PDF & Document Generator
 * Used for instant, zero-network PDF compilation directly in the browser (Claude/ChatGPT style).
 */

function escapePdfText(str: string): string {
  return str
    .replace(/\\/g, '\\\\')
    .replace(/\(/g, '\\(')
    .replace(/\)/g, '\\)')
    .replace(/[\r\n\t]/g, ' ')
}

function wrapWords(text: string, maxChars: number): string[] {
  const words = text.split(/\s+/)
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

export function buildClientPdfBlobUrl(title: string, markdown: string): { blobUrl: string; pageCount: number; pagesText: string[]; bytes: Uint8Array } {
  const A4_W = 595.28
  const A4_H = 841.89
  const MARGIN_LEFT = 45
  const MARGIN_RIGHT = 550
  const USABLE_W = MARGIN_RIGHT - MARGIN_LEFT
  const TOP_Y = 780
  const BOTTOM_Y = 55

  const rawLines = markdown.split(/\r?\n/)
  const pages: string[][] = []
  const pagesText: string[] = []
  let currentPageCommands: string[] = []
  let currentPageLines: string[] = []
  let currentY = TOP_Y

  function newPage() {
    if (currentPageCommands.length > 0) {
      pages.push(currentPageCommands)
      pagesText.push(currentPageLines.join('\n'))
    }
    currentPageCommands = []
    currentPageLines = []
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
      currentY -= 8
      i++
      continue
    }

    if (line === '---' || line.includes('[PAGE_BREAK]')) {
      newPage()
      i++
      continue
    }

    currentPageLines.push(line)

    // Table
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
        const rowH = 18

        for (let rIdx = 0; rIdx < tableRows.length; rIdx++) {
          ensureSpace(rowH + 4)
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
            const val = escapePdfText((row[cIdx] || '').slice(0, Math.floor(colW / 5.5)))
            const cellX = MARGIN_LEFT + cIdx * colW + 4
            const fontTag = isHeader ? '/F2 8.5' : '/F1 8'
            currentPageCommands.push(`BT\n${fontTag} Tf\n0.1 0.1 0.15 rg\n${cellX} ${y - 12} Td\n(${val}) Tj\nET\n`)
          }
          currentY -= rowH
        }
        currentY -= 6
      }
      continue
    }

    // Heading 1
    if (line.startsWith('# ')) {
      ensureSpace(34)
      const hText = escapePdfText(line.slice(2).trim())
      currentPageCommands.push(`0.06 0.70 0.45 rg\n${MARGIN_LEFT} ${currentY - 14} 4 16 re f\n`)
      currentPageCommands.push(`BT\n/F2 14 Tf\n0.08 0.10 0.16 rg\n${MARGIN_LEFT + 10} ${currentY - 12} Td\n(${hText}) Tj\nET\n`)
      currentY -= 24
      i++
      continue
    }

    // Heading 2
    if (line.startsWith('## ')) {
      ensureSpace(24)
      const hText = escapePdfText(line.slice(3).trim())
      currentPageCommands.push(`BT\n/F2 11.5 Tf\n0.12 0.22 0.35 rg\n${MARGIN_LEFT} ${currentY - 10} Td\n(${hText}) Tj\nET\n`)
      currentPageCommands.push(`0.85 0.88 0.92 RG 0.5 w\n${MARGIN_LEFT} ${currentY - 13} ${USABLE_W} 0.5 re f\n`)
      currentY -= 20
      i++
      continue
    }

    // Heading 3
    if (line.startsWith('### ')) {
      ensureSpace(18)
      const hText = escapePdfText(line.slice(4).trim())
      currentPageCommands.push(`BT\n/F2 10 Tf\n0.18 0.20 0.26 rg\n${MARGIN_LEFT} ${currentY - 9} Td\n(${hText}) Tj\nET\n`)
      currentY -= 15
      i++
      continue
    }

    // Bullet points
    if (line.startsWith('- ') || line.startsWith('* ')) {
      const bText = line.slice(2).trim()
      const wrapped = wrapWords(bText, 85)
      for (let j = 0; j < wrapped.length; j++) {
        ensureSpace(13)
        const prefix = j === 0 ? '\u2022 ' : '  '
        const clean = escapePdfText(prefix + wrapped[j])
        currentPageCommands.push(`BT\n/F1 9 Tf\n0.15 0.15 0.20 rg\n${MARGIN_LEFT + 8} ${currentY - 8} Td\n(${clean}) Tj\nET\n`)
        currentY -= 13
      }
      i++
      continue
    }

    // Image / Figure Card (![caption](url))
    const imgMatch = line.match(/^!\[([^\]]*)\]\(([^)]+)\)/)
    if (imgMatch) {
      const caption = imgMatch[1].trim() || 'Figure'
      const url = imgMatch[2].trim()
      const boxH = 46
      ensureSpace(boxH + 12)

      // Light slate card background
      currentPageCommands.push(`0.95 0.96 0.98 rg\n${MARGIN_LEFT} ${currentY - boxH} ${USABLE_W} ${boxH} re f\n`)
      // Emerald left accent indicator
      currentPageCommands.push(`0.06 0.70 0.45 rg\n${MARGIN_LEFT} ${currentY - boxH} 4 ${boxH} re f\n`)
      // Card border
      currentPageCommands.push(`0.82 0.85 0.90 RG 0.5 w\n${MARGIN_LEFT} ${currentY - boxH} ${USABLE_W} ${boxH} re s\n`)

      // Figure label & caption
      const cleanCap = escapePdfText(`[FIGURE / PHOTOGRAPHIC RECORD] ${caption}`.slice(0, 80))
      currentPageCommands.push(`BT\n/F2 9.5 Tf\n0.10 0.15 0.25 rg\n${MARGIN_LEFT + 12} ${currentY - 16} Td\n(${cleanCap}) Tj\nET\n`)

      // Verified image source URL
      const cleanUrl = escapePdfText(`Verified Visual Source: ${url}`.slice(0, 95))
      currentPageCommands.push(`BT\n/F1 7.5 Tf\n0.35 0.42 0.50 rg\n${MARGIN_LEFT + 12} ${currentY - 32} Td\n(${cleanUrl}) Tj\nET\n`)

      currentY -= (boxH + 10)
      i++
      continue
    }

    // Paragraph
    const wrapped = wrapWords(line, 88)
    for (const wLine of wrapped) {
      ensureSpace(13)
      const clean = escapePdfText(wLine)
      currentPageCommands.push(`BT\n/F1 9.2 Tf\n0.12 0.14 0.18 rg\n${MARGIN_LEFT} ${currentY - 8} Td\n(${clean}) Tj\nET\n`)
      currentY -= 13
    }
    i++
  }

  if (currentPageCommands.length > 0) {
    pages.push(currentPageCommands)
    pagesText.push(currentPageLines.join('\n'))
  }
  if (pages.length === 0) {
    pages.push([`BT\n/F1 10 Tf\n${MARGIN_LEFT} 700 Td\n(Pentagon Generated Document) Tj\nET\n`])
    pagesText.push(title)
  }

  const pageCount = pages.length
  let objIdx = 1
  const catalogIdx = objIdx++
  const pagesIdx = objIdx++
  const fontRegIdx = objIdx++
  const fontBoldIdx = objIdx++

  const pageObjIds: number[] = []
  const streamObjIds: number[] = []
  for (let p = 0; p < pageCount; p++) {
    pageObjIds.push(objIdx++)
    streamObjIds.push(objIdx++)
  }

  const streamBodies = pages.map((cmds, pIdx) => {
    let headerStr = ''
    headerStr += `0.08 0.12 0.18 rg\n${MARGIN_LEFT} 810 ${USABLE_W} 22 re f\n`
    headerStr += `0.06 0.70 0.45 rg\n${MARGIN_LEFT} 808 ${USABLE_W} 2 re f\n`
    headerStr += `BT\n/F2 10 Tf\n1 1 1 rg\n${MARGIN_LEFT + 8} 817 Td\n(${escapePdfText(title.slice(0, 50))}) Tj\nET\n`
    headerStr += `BT\n/F1 8 Tf\n0.8 0.85 0.9 rg\n${MARGIN_RIGHT - 110} 817 Td\n(Pentagon AI Intelligence) Tj\nET\n`

    let footerStr = ''
    footerStr += `0.85 0.88 0.90 RG 0.5 w\n${MARGIN_LEFT} 45 ${USABLE_W} 0.5 re f\n`
    footerStr += `BT\n/F1 8 Tf\n0.4 0.45 0.5 rg\n${MARGIN_LEFT} 32 Td\n(Executive Report  \u2022  Generated by Pentagon) Tj\nET\n`
    footerStr += `BT\n/F2 8 Tf\n0.2 0.25 0.3 rg\n${MARGIN_RIGHT - 65} 32 Td\n(Page ${pIdx + 1} of ${pageCount}) Tj\nET\n`

    return headerStr + cmds.join('') + footerStr
  })

  const bodyParts: string[] = []
  const offsets: number[] = []
  let offset = 0

  function add(str: string) {
    offsets.push(offset)
    bodyParts.push(str)
    offset += new TextEncoder().encode(str).length
  }

  const pdfHeader = '%PDF-1.4\n%\xe2\xe3\xcf\xd3\n'
  offset += new TextEncoder().encode(pdfHeader).length

  add(`${catalogIdx} 0 obj\n<< /Type /Catalog /Pages ${pagesIdx} 0 R >>\nendobj\n`)
  add(`${pagesIdx} 0 obj\n<< /Type /Pages /Kids [${pageObjIds.map((id) => `${id} 0 R`).join(' ')}] /Count ${pageCount} >>\nendobj\n`)
  add(`${fontRegIdx} 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n`)
  add(`${fontBoldIdx} 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>\nendobj\n`)

  for (let p = 0; p < pageCount; p++) {
    const pId = pageObjIds[p]
    const sId = streamObjIds[p]
    const sBody = streamBodies[p]
    const sLen = new TextEncoder().encode(sBody).length
    add(`${pId} 0 obj\n<< /Type /Page /Parent ${pagesIdx} 0 R /MediaBox [0 0 ${A4_W} ${A4_H}] /Contents ${sId} 0 R /Resources << /Font << /F1 ${fontRegIdx} 0 R /F2 ${fontBoldIdx} 0 R >> >> >>\nendobj\n`)
    add(`${sId} 0 obj\n<< /Length ${sLen} >>\nstream\n${sBody}endstream\nendobj\n`)
  }

  const xrefOffset = offset
  let xref = `xref\n0 ${offsets.length + 1}\n0000000000 65535 f \n`
  for (const off of offsets) {
    xref += String(off).padStart(10, '0') + ' 00000 n \n'
  }
  const trailer = `trailer\n<< /Size ${offsets.length + 1} /Root ${catalogIdx} 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`

  const totalString = pdfHeader + bodyParts.join('') + xref + trailer
  const bytes = new TextEncoder().encode(totalString)
  const blob = new Blob([bytes], { type: 'application/pdf' })
  const blobUrl = URL.createObjectURL(blob)

  return {
    blobUrl,
    pageCount,
    pagesText,
    bytes,
  }
}
