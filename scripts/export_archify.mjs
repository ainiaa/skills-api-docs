#!/usr/bin/env node
// Drive the export controls in the HTML delivered by the pinned official Archify CLI.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const [cliPath, htmlPath, outputDir, ...formats] = process.argv.slice(2);
if (!cliPath || !htmlPath || !outputDir || !formats.length) {
  console.error('usage: export_archify.mjs <archify-cli> <html> <output-dir> <formats...>');
  process.exit(2);
}

const official = await import(pathToFileURL(path.join(path.dirname(fs.realpathSync(cliPath)), 'visual-check.mjs')));
const chrome = official.findChrome();
if (!chrome) {
  console.error('Chrome/Chromium is required for Archify viewer exports');
  process.exit(2);
}

const browser = new official.ChromeVisualBrowser(chrome);
const downloadRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'archify-export-'));
try {
  const session = await browser.sessionPromise;
  await browser.cdp.send('Emulation.setDeviceMetricsOverride', {
    width: 1440, height: 900, deviceScaleFactor: 1, mobile: false,
  }, session);
  const loaded = browser.cdp.waitFor('Page.loadEventFired', session);
  const navigated = await browser.cdp.send('Page.navigate', { url: pathToFileURL(htmlPath).href }, session);
  if (navigated.errorText) throw new Error(navigated.errorText);
  await loaded;
  const ready = await browser.cdp.send('Runtime.evaluate', {
    expression: `(async () => {
      await (document.fonts?.ready || Promise.resolve());
      await window.Archify?.readerLayout?.whenStable?.();
      await window.Archify?.viewerChromeLayout?.whenStable?.();
      if (!window.Archify?.exportMenu?.run) throw new Error('Archify export menu is unavailable');
      return true;
    })()`,
    awaitPromise: true, returnByValue: true,
  }, session);
  if (ready.exceptionDetails || ready.result?.value !== true) throw new Error('Archify viewer did not initialize');

  for (const format of formats) {
    const target = path.join(outputDir, `architecture.archify.${format}`);
    if (format === 'pdf') {
      const printed = await browser.cdp.send('Page.printToPDF', {
        printBackground: true, preferCSSPageSize: true,
      }, session);
      fs.writeFileSync(target, Buffer.from(printed.data, 'base64'));
      continue;
    }
    const viewerFormat = format === 'jpg' ? 'jpeg' : format;
    const downloadDir = path.join(downloadRoot, format);
    fs.mkdirSync(downloadDir);
    await browser.cdp.send('Page.setDownloadBehavior', {
      behavior: 'allow', downloadPath: downloadDir,
    }, session);
    const response = await browser.cdp.send('Runtime.evaluate', {
      expression: `Archify.exportMenu.run(${JSON.stringify(viewerFormat)})`,
      awaitPromise: true, returnByValue: true, userGesture: true,
    }, session);
    if (response.exceptionDetails) throw new Error(`Archify ${format} export failed`);
    const receipt = await browser.cdp.send('Runtime.evaluate', {
      expression: `({ format: document.documentElement.getAttribute('data-last-export-format'),
        bytes: Number(document.documentElement.getAttribute('data-last-export-bytes')),
        canonical: document.documentElement.getAttribute('data-last-export-canonical'),
        error: document.documentElement.getAttribute('data-last-export-error') })`,
      returnByValue: true,
    }, session);
    const proof = receipt.result?.value;
    if (proof?.format !== viewerFormat || !Number.isFinite(proof.bytes) || proof.bytes <= 0 ||
        proof.canonical !== 'true' || proof.error) {
      throw new Error(`Archify ${format} export receipt failed: ${JSON.stringify(proof)}`);
    }
    let downloaded;
    for (let attempt = 0; attempt < 100; attempt++) {
      downloaded = fs.readdirSync(downloadDir).find((name) =>
        !name.endsWith('.crdownload') && fs.statSync(path.join(downloadDir, name)).size === proof.bytes);
      if (downloaded) break;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    if (!downloaded) throw new Error(`Archify ${format} download was not completed`);
    fs.copyFileSync(path.join(downloadDir, downloaded), target);
  }
} catch (error) {
  console.error(error?.stack || String(error));
  process.exitCode = 1;
} finally {
  await browser.close();
  fs.rmSync(downloadRoot, { recursive: true, force: true });
}
