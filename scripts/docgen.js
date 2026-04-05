#!/usr/bin/env node
/**
 * docgen.js — Convert a markdown analysis report to a Word document
 *
 * Usage:
 *   node scripts/docgen.js ./output/my-analysis.md
 *   node scripts/docgen.js ./output/my-analysis.md ./output/my-analysis.docx
 *
 * Requires: npm install docx
 */

const fs = require('fs');
const path = require('path');

// ── Check docx is installed ───────────────────────────────────────────────────
let docx;
try {
  docx = require('docx');
} catch (e) {
  console.error('docx package not found. Run: npm install docx');
  process.exit(1);
}

const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, VerticalAlign, PageNumber, PageBreak, LevelFormat,
} = docx;

// ── Args ──────────────────────────────────────────────────────────────────────
const inputFile = process.argv[2];
if (!inputFile) {
  console.error('Usage: node scripts/docgen.js <input.md> [output.docx]');
  process.exit(1);
}

if (!fs.existsSync(inputFile)) {
  console.error(`File not found: ${inputFile}`);
  process.exit(1);
}

const outputFile = process.argv[3] ||
  inputFile.replace(/\.md$/, '.docx').replace('/output/', '/output/');

const markdown = fs.readFileSync(inputFile, 'utf8');

// ── Colours ───────────────────────────────────────────────────────────────────
const BLUE    = "1F3864";
const LBLUE   = "2E75B6";
const LLBLUE  = "D6E4F0";
const LLGREY  = "F2F2F2";
const WHITE   = "FFFFFF";
const REDFILL = "FCE4D6";
const AMBERFILL = "FFF2CC";

// ── Helpers ───────────────────────────────────────────────────────────────────
const border  = (color = "CCCCCC") => ({ style: BorderStyle.SINGLE, size: 1, color });
const borders = (color = "CCCCCC") => ({
  top: border(color), bottom: border(color),
  left: border(color), right: border(color)
});

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 360, after: 160 },
    shading: { fill: BLUE, type: ShadingType.CLEAR },
    indent: { left: 180 },
    children: [new TextRun({ text, bold: true, size: 32, color: WHITE, font: "Arial" })],
  });
}

function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 280, after: 120 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: LBLUE, space: 1 } },
    children: [new TextRun({ text, bold: true, size: 26, color: BLUE, font: "Arial" })],
  });
}

function h3(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3,
    spacing: { before: 200, after: 80 },
    children: [new TextRun({ text, bold: true, size: 22, color: LBLUE, font: "Arial" })],
  });
}

function para(text) {
  return new Paragraph({
    spacing: { before: 60, after: 60 },
    children: [new TextRun({ text, size: 20, font: "Arial" })],
  });
}

function bullet(text, level = 0) {
  return new Paragraph({
    numbering: { reference: "bullets", level },
    spacing: { before: 40, after: 40 },
    children: [new TextRun({ text, size: 20, font: "Arial" })],
  });
}

function codeBlock(text) {
  return new Paragraph({
    spacing: { before: 40, after: 40 },
    shading: { fill: "F4F4F8", type: ShadingType.CLEAR },
    indent: { left: 360 },
    children: [new TextRun({ text, font: "Courier New", size: 16, color: "7030A0" })],
  });
}

function spacer() {
  return new Paragraph({ spacing: { before: 80, after: 80 }, children: [new TextRun("")] });
}

function pageBreak() {
  return new Paragraph({ children: [new PageBreak()] });
}

// ── Markdown parser ───────────────────────────────────────────────────────────
// Simple line-by-line parser — handles headings, bullets, code blocks, tables
function parseMarkdown(md) {
  const lines = md.split('\n');
  const elements = [];
  let inCode = false;
  let inTable = false;
  let tableRows = [];

  const flushTable = () => {
    if (tableRows.length < 2) { tableRows = []; inTable = false; return; }

    // First row = headers, second row = separator (skip), rest = data
    const headers = tableRows[0].split('|').map(s => s.trim()).filter(Boolean);
    const dataRows = tableRows.slice(2).map(r =>
      r.split('|').map(s => s.trim()).filter(Boolean)
    );

    const colWidth = Math.floor(9360 / headers.length);
    const colWidths = headers.map(() => colWidth);

    const headerRow = new TableRow({
      tableHeader: true,
      children: headers.map(h => new TableCell({
        width: { size: colWidth, type: WidthType.DXA },
        borders: borders("2E75B6"),
        shading: { fill: LLBLUE, type: ShadingType.CLEAR },
        margins: { top: 80, bottom: 80, left: 120, right: 120 },
        children: [new Paragraph({
          children: [new TextRun({ text: h, bold: true, size: 18, font: "Arial", color: BLUE })]
        })],
      })),
    });

    const rows = dataRows.map((row, ri) => new TableRow({
      children: headers.map((_, ci) => new TableCell({
        width: { size: colWidth, type: WidthType.DXA },
        borders: borders(),
        shading: { fill: ri % 2 === 0 ? WHITE : LLGREY, type: ShadingType.CLEAR },
        margins: { top: 80, bottom: 80, left: 120, right: 120 },
        children: [new Paragraph({
          children: [new TextRun({ text: row[ci] || '', size: 18, font: "Arial" })]
        })],
      })),
    }));

    elements.push(new Table({
      width: { size: 9360, type: WidthType.DXA },
      rows: [headerRow, ...rows],
    }));
    elements.push(spacer());

    tableRows = [];
    inTable = false;
  };

  for (const line of lines) {
    // Code block toggle
    if (line.startsWith('```')) {
      inCode = !inCode;
      continue;
    }

    if (inCode) {
      if (line.trim()) elements.push(codeBlock(line));
      continue;
    }

    // Table row
    if (line.startsWith('|')) {
      inTable = true;
      tableRows.push(line);
      continue;
    } else if (inTable) {
      flushTable();
    }

    // Headings
    if (line.startsWith('# '))        { elements.push(h1(line.slice(2).trim())); continue; }
    if (line.startsWith('## '))       { elements.push(h2(line.slice(3).trim())); continue; }
    if (line.startsWith('### '))      { elements.push(h3(line.slice(4).trim())); continue; }
    if (line.startsWith('#### '))     { elements.push(h3(line.slice(5).trim())); continue; }

    // Bullets
    if (line.match(/^[-*] /))  { elements.push(bullet(line.slice(2).trim(), 0)); continue; }
    if (line.match(/^  [-*] /)) { elements.push(bullet(line.slice(4).trim(), 1)); continue; }

    // Horizontal rule
    if (line.match(/^---+$/))  { elements.push(spacer()); continue; }

    // Empty line
    if (line.trim() === '')    { elements.push(spacer()); continue; }

    // Regular paragraph
    // Strip inline markdown (bold, italic, code)
    const clean = line
      .replace(/\*\*(.*?)\*\*/g, '$1')
      .replace(/\*(.*?)\*/g, '$1')
      .replace(/`(.*?)`/g, '$1')
      .replace(/\[(.*?)\]\(.*?\)/g, '$1');

    elements.push(para(clean));
  }

  if (inTable) flushTable();

  return elements;
}

// ── Build document ────────────────────────────────────────────────────────────
console.log(`Converting: ${inputFile}`);
console.log(`Output:     ${outputFile}`);

const children = parseMarkdown(markdown);

const doc = new Document({
  numbering: {
    config: [{
      reference: "bullets",
      levels: [
        {
          level: 0,
          format: LevelFormat.BULLET,
          text: "•",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } },
        },
        {
          level: 1,
          format: LevelFormat.BULLET,
          text: "◦",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 1080, hanging: 360 } } },
        },
      ],
    }],
  },
  sections: [{
    properties: {
      page: {
        size: { width: 15840, height: 12240 },
        margin: { top: 720, right: 720, bottom: 720, left: 720 },
        orientation: "landscape",
      },
    },
    headers: {
      default: new Header({
        children: [new Paragraph({
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: LBLUE, space: 1 } },
          children: [new TextRun({
            text: `Salesforce Org Analysis  |  ${path.basename(inputFile, '.md')}`,
            size: 16, font: "Arial", color: "888888"
          })],
        })],
      }),
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          border: { top: { style: BorderStyle.SINGLE, size: 4, color: LBLUE, space: 1 } },
          children: [
            new TextRun({ text: "Page ", size: 16, font: "Arial", color: "888888" }),
            new TextRun({ children: [PageNumber.CURRENT], size: 16, font: "Arial", color: "888888" }),
            new TextRun({ text: " of ", size: 16, font: "Arial", color: "888888" }),
            new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 16, font: "Arial", color: "888888" }),
          ],
        })],
      }),
    },
    children,
  }],
});

Packer.toBuffer(doc).then(buffer => {
  fs.mkdirSync(path.dirname(outputFile), { recursive: true });
  fs.writeFileSync(outputFile, buffer);
  const size = (buffer.length / 1024).toFixed(1);
  console.log(`✅ Done — ${outputFile} (${size} KB)`);
}).catch(err => {
  console.error('Error generating document:', err.message);
  process.exit(1);
});
