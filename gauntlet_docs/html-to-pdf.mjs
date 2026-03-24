import puppeteer from 'puppeteer';
import { readFileSync } from 'fs';
import { resolve } from 'path';

const htmlPath = resolve('PRESEARCH.html');
let html = readFileSync(htmlPath, 'utf-8');

// Inject CSS for proper formatting
const css = `
<style>
  body {
    font-family: 'Segoe UI', sans-serif;
    font-size: 11pt;
    line-height: 1.5;
    max-width: 800px;
    margin: 0 auto;
    padding: 40px 60px;
    color: #222;
  }
  h1 { font-size: 20pt; margin-top: 1.5em; }
  h2 { font-size: 16pt; margin-top: 1.5em; }
  h3 { font-size: 13pt; margin-top: 1.2em; }
  h4 { font-size: 11pt; margin-top: 1em; }
  ul, ol { margin-left: 1.5em; padding-left: 0.5em; }
  li { margin-bottom: 0.5em; }
  code { font-family: Consolas, monospace; background: #f4f4f4; padding: 1px 4px; font-size: 10pt; }
  pre { background: #f4f4f4; padding: 12px; overflow-x: auto; font-size: 9pt; }
  pre code { background: none; padding: 0; }
  blockquote { border-left: 3px solid #ccc; margin-left: 0; padding-left: 1em; color: #555; }
  hr { border: none; border-top: 1px solid #ccc; margin: 2em 0; }
  p { margin-bottom: 0.6em; }
</style>
`;

html = html.replace('</head>', css + '</head>');

const browser = await puppeteer.launch({ headless: true });
const page = await browser.newPage();
await page.setContent(html, { waitUntil: 'networkidle0' });
await page.pdf({
  path: 'PRESEARCH.pdf',
  format: 'Letter',
  margin: { top: '1in', bottom: '1in', left: '1in', right: '1in' },
  printBackground: true,
});
await browser.close();
console.log('PDF created successfully');
