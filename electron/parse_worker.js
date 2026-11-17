'use strict';
/**
 * Worker thread: parses PDF / DOCX / text files OFF the Electron main thread so the UI never freezes.
 * Messages in : { id, filePath }
 * Messages out: { id, ok: true, text, pages } | { id, ok: false, code, message }
 */
const { parentPort } = require('worker_threads');
const fs = require('fs');
const path = require('path');

const MAX_BYTES = 25 * 1024 * 1024;

function normalize(text) {
  return text.replace(/\r\n?/g, '\n').replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
}
function countWords(text) {
  return text ? text.split(/\s+/).filter(Boolean).length : 0;
}
function fail(code, message) {
  const e = new Error(message);
  e.code = code;
  throw e;
}

async function extractText(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  const stat = fs.statSync(filePath);
  if (stat.size === 0) fail('empty', 'The file is empty.');
  if (stat.size > MAX_BYTES) fail('too_large', 'File is larger than 25 MB.');
  const buffer = fs.readFileSync(filePath);

  if (ext === '.pdf') {
    let text = '';
    let pages = null;
    try {
      const { PDFParse } = require('pdf-parse');
      const parser = new PDFParse({ data: buffer });
      try {
        const result = await parser.getText();
        pages = result.total || null;
        text = normalize(String(result.text || '').replace(/^\s*-- \d+ of \d+ --\s*$/gm, ''));
      } finally {
        await parser.destroy().catch(() => {});
      }
    } catch (e) {
      const name = (e && e.name) || '';
      const msg = String((e && e.message) || e);
      if (name === 'PasswordException' || /password|encrypt/i.test(msg)) fail('encrypted', 'The PDF is password-protected; remove the password and upload again.');
      if (name === 'InvalidPDFException' || name === 'FormatError' || /invalid pdf|xref|corrupt/i.test(msg)) fail('corrupted', 'The PDF appears to be corrupted or is not a valid PDF.');
      fail('read_error', `Could not read PDF: ${msg.slice(0, 160)}`);
    }
    if (countWords(text) < 15) fail('no_text', `No extractable text found (${pages || '?'} page(s)). This looks like a scanned/image-only PDF - run OCR or export it as text first.`);
    return { text, pages };
  }

  if (ext === '.docx') {
    let result;
    try {
      const mammoth = require('mammoth');
      result = await mammoth.extractRawText({ buffer });
    } catch (e) {
      const msg = String((e && e.message) || e);
      if (/zip|end of central directory|not a valid/i.test(msg)) fail('corrupted', 'The .docx is corrupted or is not a Word document (old .doc files are not supported).');
      if (/encrypt|password/i.test(msg)) fail('encrypted', 'The .docx is password-protected.');
      fail('read_error', `Could not read DOCX: ${msg.slice(0, 160)}`);
    }
    const text = normalize(result.value || '');
    if (countWords(text) < 5) fail('no_text', 'The Word document contains no readable text.');
    return { text, pages: null };
  }

  if (ext === '.txt' || ext === '.md' || ext === '.markdown') {
    let text = buffer.toString('utf8');
    if (text.includes('�')) text = buffer.toString('latin1');
    text = normalize(text.replace(/^﻿/, ''));
    if (countWords(text) < 2) fail('no_text', 'The text file is empty.');
    return { text, pages: null };
  }
  fail('unsupported', `Unsupported file type "${ext}". Use .pdf, .docx, .txt or .md.`);
}

parentPort.on('message', async ({ id, filePath }) => {
  try {
    const { text, pages } = await extractText(filePath);
    parentPort.postMessage({ id, ok: true, text, pages });
  } catch (e) {
    parentPort.postMessage({ id, ok: false, code: e.code || 'read_error', message: e.message });
  }
});
