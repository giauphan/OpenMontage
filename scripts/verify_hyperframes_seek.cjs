#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const crypto = require('node:crypto');


const MAX_DURATION_SECONDS = 60 * 60;
const DEFAULT_VIEWPORT = { width: 1080, height: 1920 };
const MIME_TYPES = {
  '.css': 'text/css; charset=utf-8', '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8', '.json': 'application/json; charset=utf-8',
  '.mp3': 'audio/mpeg', '.mp4': 'video/mp4', '.ogg': 'audio/ogg', '.png': 'image/png',
  '.svg': 'image/svg+xml', '.ttf': 'font/ttf', '.wav': 'audio/wav', '.webm': 'video/webm',
  '.woff': 'font/woff', '.woff2': 'font/woff2', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
};

function usage() {
  return `Usage:\n  node scripts/verify_hyperframes_seek.cjs <composition-dir> --options <json-file> --output <dir> [--root <html-file>] [--playwright-module <file-or-dir>] [--executable-path <browser>]\n\nOptions JSON:\n  {\n    "timelineId": "main",\n    "samples": [\n      {"time": 2, "activeScene": "scene-hero"},\n      {"time": 10, "activeScene": "scene-data"}\n    ]\n  }\n\nScene values are CSS selectors; plain IDs are treated as #IDs. Each sample is\nchecked on forward seek, reverse seek, and a repeated seek. --root is relative\nto the composition directory (default: index.html). Playwright can also be\nselected with PLAYWRIGHT_MODULE; browser binary with PLAYWRIGHT_EXECUTABLE_PATH.\nThis tests a direct GSAP timeline in a real browser, not HyperFrames renderer parity.`;
}

function fail(message) {
  throw new Error(message);
}

function parseArgs(argv) {
  const args = { positional: [] };
  const valueOptions = new Set(['options', 'output', 'root', 'playwright-module', 'executable-path']);
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--help' || arg === '-h') { args.help = true; continue; }
    if (!arg.startsWith('--')) { args.positional.push(arg); continue; }
    const name = arg.slice(2);
    if (!valueOptions.has(name)) fail(`Unknown option: ${arg}`);
    if (args[name] || !argv[i + 1] || argv[i + 1].startsWith('--')) fail(`Missing value for ${arg}`);
    args[name] = argv[++i];
  }
  return args;
}

function loadPlaywright(moduleArg) {
  const requested = moduleArg || process.env.PLAYWRIGHT_MODULE;
  const candidates = requested ? [requested] : ['playwright'];
  for (const candidate of candidates) {
    try {
      const resolved = path.isAbsolute(candidate) || candidate.startsWith('.')
        ? require.resolve(path.resolve(candidate))
        : require.resolve(candidate, { paths: [process.cwd(), __dirname] });
      const playwright = require(resolved);
      if (playwright && playwright.chromium) return { playwright, resolved };
      fail(`Module ${candidate} does not export Playwright's chromium API`);
    } catch (error) {
      if (requested) throw new Error(`Cannot load Playwright module ${candidate}: ${error.message}`);
    }
  }
  fail('Playwright is not resolvable. Pass --playwright-module or set PLAYWRIGHT_MODULE.');
}

function normalizeSelector(value) {
  if (typeof value !== 'string' || !value.trim()) fail('Each sample needs a non-empty activeScene selector');
  const selector = value.trim();
  return /^[A-Za-z_][\w-]*$/.test(selector) ? `#${selector}` : selector;
}

function readOptions(file) {
  let options;
  try { options = JSON.parse(fs.readFileSync(file, 'utf8')); }
  catch (error) { fail(`Cannot read JSON options ${file}: ${error.message}`); }
  if (!options || typeof options !== 'object' || Array.isArray(options)) fail('Options JSON must be an object');
  if (!Array.isArray(options.samples) || options.samples.length < 2) fail('Options must contain at least two samples');
  const samples = options.samples.map((sample, index) => {
    if (!sample || typeof sample !== 'object' || Array.isArray(sample)) fail(`Sample ${index} must be an object`);
    if (!Number.isFinite(sample.time) || sample.time < 0) fail(`Sample ${index} has invalid time`);
    const activeScene = normalizeSelector(sample.activeScene || sample.expectedActiveScene);
    return { time: sample.time, activeScene };
  });
  if (new Set(samples.map((sample) => sample.time)).size !== samples.length) fail('Sample times must be unique');
  if (new Set(samples.map((sample) => sample.activeScene)).size < 2) fail('Samples must expect at least two distinct active scenes');
  return { timelineId: options.timelineId, samples, sceneSelector: options.sceneSelector || '[data-scene-id], .scene' };
}

function startStaticServer(directory) {
  const server = http.createServer((request, response) => {
    let pathname;
    try { pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname); }
    catch { response.writeHead(400).end('Bad request'); return; }
    const relative = pathname.replace(/^\/+/, '') || 'index.html';
    const target = path.resolve(directory, relative);
    if (target !== directory && !target.startsWith(`${directory}${path.sep}`)) {
      response.writeHead(403).end('Forbidden'); return;
    }
    fs.stat(target, (statError, stat) => {
      if (statError || !stat.isFile()) { response.writeHead(404).end('Not found'); return; }
      response.writeHead(200, {
        'Content-Type': MIME_TYPES[path.extname(target).toLowerCase()] || 'application/octet-stream',
        'Cache-Control': 'no-store',
        'Content-Length': stat.size,
      });
      fs.createReadStream(target).pipe(response);
    });
  });
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      server.removeListener('error', reject);
      resolve({ server, url: `http://127.0.0.1:${server.address().port}/` });
    });
  });
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) { process.stdout.write(`${usage()}\n`); return; }
  if (args.positional.length !== 1 || !args.options || !args.output) fail(usage());

  const compositionDir = path.resolve(args.positional[0]);
  const rootFile = path.resolve(compositionDir, args.root || 'index.html');
  const outputDir = path.resolve(args.output);
  if (!fs.statSync(compositionDir).isDirectory()) fail(`Composition path is not a directory: ${compositionDir}`);
  if (!rootFile.startsWith(`${compositionDir}${path.sep}`) || !fs.statSync(rootFile).isFile()) fail(`Root HTML is missing or outside composition directory: ${rootFile}`);
  const options = readOptions(path.resolve(args.options));
  const { playwright, resolved: playwrightModule } = loadPlaywright(args['playwright-module']);
  fs.mkdirSync(outputDir, { recursive: true });

  const samples = options.samples;
  const maxTime = Math.max(...samples.map((sample) => sample.time));
  const browserArgs = { headless: true };
  const executablePath = args['executable-path'] || process.env.PLAYWRIGHT_EXECUTABLE_PATH;
  if (executablePath) browserArgs.executablePath = path.resolve(executablePath);
  let browser;
  let server;
  const pageErrors = [];
  const requestFailures = [];
  const report = {
    status: 'failed', mode: 'direct-gsap-timeline-browser-harness',
    compositionDir, rootFile, outputDir, playwrightModule,
    executablePath: browserArgs.executablePath || null,
    timelineId: options.timelineId || null, samples: [], failures: [],
  };
  try {
    const serving = await startStaticServer(compositionDir);
    server = serving.server;
    browser = await playwright.chromium.launch(browserArgs);
    const page = await browser.newPage({ viewport: DEFAULT_VIEWPORT, deviceScaleFactor: 1 });
    page.on('pageerror', (error) => pageErrors.push(error.stack || error.message));
    page.on('requestfailed', (request) => requestFailures.push(`${request.url()}: ${request.failure()?.errorText || 'request failed'}`));
    const targetUrl = new URL(path.relative(compositionDir, rootFile).split(path.sep).map(encodeURIComponent).join('/'), serving.url).toString();
    const response = await page.goto(targetUrl, { waitUntil: 'load', timeout: 60000 });
    if (!response || !response.ok()) fail(`Composition returned HTTP ${response ? response.status() : 'no response'}`);
    await page.evaluate(async () => {
      await document.fonts.ready;
      const images = Array.from(document.images);
      await Promise.all(images.map((image) => image.decode().catch(() => {})));
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    });

    const timelineInfo = await page.evaluate(({ timelineId, maxDuration, maxSampleTime }) => {
      const roots = Array.from(document.querySelectorAll('[data-composition-id]'));
      if (!roots.length) throw new Error('No [data-composition-id] root found');
      const keys = Object.keys(window.__timelines || {});
      const id = timelineId || roots[0].getAttribute('data-composition-id');
      if (!id || !roots.some((root) => root.getAttribute('data-composition-id') === id)) {
        throw new Error(`No composition root matches timeline ID ${id}`);
      }
      const timeline = window.__timelines && window.__timelines[id];
      if (!timeline || typeof timeline.time !== 'function' || typeof timeline.duration !== 'function') {
        throw new Error(`No seekable window.__timelines[${JSON.stringify(id)}]; registered keys: ${keys.join(', ') || '(none)'}`);
      }
      const duration = timeline.duration();
      const declared = Number(roots.find((root) => root.getAttribute('data-composition-id') === id).getAttribute('data-duration'));
      if (!Number.isFinite(duration) || duration <= 0 || duration > maxDuration) throw new Error(`Invalid/excessive timeline duration: ${duration}`);
      if (!Number.isFinite(declared) || declared <= 0 || declared > maxDuration) throw new Error(`Invalid/excessive data-duration: ${declared}`);
      if (maxSampleTime > duration || maxSampleTime > declared) throw new Error(`Sample time ${maxSampleTime}s exceeds timeline/data-duration ${duration}/${declared}s`);
      if (Math.abs(duration - declared) > 0.05) throw new Error(`Timeline duration ${duration}s differs from root data-duration ${declared}s`);
      const gsap = window.gsap;
      if (!gsap || !gsap.globalTimeline) throw new Error('GSAP global timeline is not available');
      const running = gsap.globalTimeline.getChildren(true, true, true)
        .filter((animation) => animation.isActive() && !animation.paused())
        .map((animation) => ({ targets: animation.targets().map((target) => target.id || target.tagName || String(target)), repeat: animation.repeat(), duration: animation.duration() }));
      if (running.length) throw new Error(`Standalone running GSAP animation(s) detected: ${JSON.stringify(running)}`);
      return { id, duration, declaredDuration: declared, rootCount: roots.length, registeredKeys: keys };
    }, { timelineId: options.timelineId, maxDuration: MAX_DURATION_SECONDS, maxSampleTime: maxTime });
    report.timelineId = timelineInfo.id;
    report.timeline = timelineInfo;

    const sceneCount = await page.locator(options.sceneSelector).count();
    if (sceneCount < 2) fail(`Scene selector ${JSON.stringify(options.sceneSelector)} matched fewer than two scenes`);

    const capture = async (sample, phase, index) => {
      const visibility = await page.evaluate(({ id, time, selector, expected }) => {
        const timeline = window.__timelines[id];
        timeline.pause();
        timeline.time(time, false);
        const nodes = Array.from(document.querySelectorAll(selector));
        const effectiveOpacity = (node) => {
          let opacity = 1;
          for (let ancestor = node; ancestor; ancestor = ancestor.parentElement) {
            const value = Number(getComputedStyle(ancestor).opacity);
            if (!Number.isFinite(value)) return 0;
            opacity *= value;
          }
          return opacity;
        };
        const sceneInfo = nodes.map((node) => {
          const style = getComputedStyle(node);
          const rect = node.getBoundingClientRect();
          const opacity = Number(style.opacity);
          const effective = effectiveOpacity(node);
          const visible = style.display !== 'none' && style.visibility !== 'hidden' && Number.isFinite(opacity) && effective > 0.15 && rect.width > 0 && rect.height > 0;
          return { id: node.id || node.getAttribute('data-scene-id') || null, opacity, effectiveOpacity: effective, visible };
        });
        const expectedNode = document.querySelector(expected);
        if (!expectedNode) throw new Error(`Expected scene selector did not match: ${expected}`);
        const style = getComputedStyle(expectedNode);
        const rect = expectedNode.getBoundingClientRect();
        const opacity = Number(style.opacity);
        const expectedEffectiveOpacity = effectiveOpacity(expectedNode);
        const expectedVisible = style.display !== 'none' && style.visibility !== 'hidden' && Number.isFinite(opacity) && expectedEffectiveOpacity > 0.15 && rect.width > 0 && rect.height > 0;
        if (!expectedVisible) throw new Error(`Expected scene ${expected} is not visible at ${time}s (opacity=${style.opacity}, effectiveOpacity=${expectedEffectiveOpacity}, display=${style.display}, visibility=${style.visibility})`);
        const expectedSceneIndex = nodes.indexOf(expectedNode);
        if (expectedSceneIndex < 0 || !sceneInfo[expectedSceneIndex].visible) {
          throw new Error(`Expected scene ${expected} was not among visible scene nodes`);
        }
        const visibleIndexes = sceneInfo.map((scene, index) => scene.visible ? index : -1).filter((index) => index >= 0);
        if (visibleIndexes.length !== 1 || visibleIndexes[0] !== expectedSceneIndex) {
          const visibleIds = visibleIndexes.map((index) => sceneInfo[index].id || `<scene-${index}>`);
          throw new Error(`Expected exactly ${expected} to be visible at ${time}s; visible scenes: ${visibleIds.join(', ') || '(none)'}`);
        }

        return { actualVisibleScenes: visibleIndexes.map((index) => sceneInfo[index].id), scenes: sceneInfo };
      }, { id: timelineInfo.id, time: sample.time, selector: options.sceneSelector, expected: sample.activeScene });
      await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      const fileName = `${String(index + 1).padStart(3, '0')}-${phase}-${sample.time.toFixed(3)}s.png`;
      const screenshot = await page.screenshot({ path: path.join(outputDir, fileName), fullPage: false, animations: 'allow' });
      return {
        time: sample.time, expectedActiveScene: sample.activeScene,
        actualVisibleScenes: visibility.actualVisibleScenes, sceneState: visibility.scenes,
        screenshot: fileName, screenshotSha256: crypto.createHash('sha256').update(screenshot).digest('hex'),
      };
    };

    const forward = [];
    for (let i = 0; i < samples.length; i += 1) forward.push(await capture(samples[i], 'forward', i));
    const reverse = [];
    for (let i = samples.length - 1; i >= 0; i -= 1) reverse.push(await capture(samples[i], 'reverse', i));
    const repeated = [];
    for (let i = 0; i < samples.length; i += 1) repeated.push(await capture(samples[i], 'repeat', i));

    const reverseBySample = new Map(reverse.map((entry) => [entry.time, entry]));
    const repeatedBySample = new Map(repeated.map((entry) => [entry.time, entry]));
    for (let i = 0; i < forward.length; i += 1) {
      const first = forward[i];
      for (const [phase, second] of [['reverse', reverseBySample.get(first.time)], ['repeat', repeatedBySample.get(first.time)]]) {
        if (first.screenshotSha256 !== second.screenshotSha256) fail(`Non-deterministic screenshot on ${phase} seek at ${first.time}s`);
        if (JSON.stringify(first.sceneState) !== JSON.stringify(second.sceneState)) fail(`Non-deterministic scene state on ${phase} seek at ${first.time}s`);
      }
    }
    const representativeImageByScene = new Map();
    for (const entry of forward) {
      if (!representativeImageByScene.has(entry.expectedActiveScene)) {
        representativeImageByScene.set(entry.expectedActiveScene, entry.screenshotSha256);
      }
    }
    if (new Set(representativeImageByScene.values()).size !== representativeImageByScene.size) {
      fail('Different expected active scenes produced identical representative screenshots');
    }

    report.samples = samples.map((sample, index) => ({
      forward: forward[index], reverse: reverseBySample.get(sample.time), repeated: repeatedBySample.get(sample.time),
    }));
    report.pageErrors = pageErrors;
    report.requestFailures = requestFailures;
    if (pageErrors.length) fail(`Browser JavaScript error(s): ${pageErrors.join(' | ')}`);
    if (requestFailures.length) fail(`Browser request failure(s): ${requestFailures.join(' | ')}`);
    report.status = 'passed';
    process.stdout.write(`PASS: ${samples.length} samples sought forward, reverse, and repeatedly; screenshots in ${outputDir}\n`);
  } catch (error) {
    report.failures.push(error.stack || error.message);
    report.pageErrors = pageErrors;
    report.requestFailures = requestFailures;
    process.stderr.write(`FAIL: ${error.message}\n`);
    process.exitCode = 1;
  } finally {
    try { if (browser) await browser.close(); }
    catch (error) { report.failures.push(`Browser close failed: ${error.message}`); report.status = 'failed'; process.exitCode = 1; }
    if (server) {
      await new Promise((resolve) => server.close((error) => {
        if (error) { report.failures.push(`HTTP server close failed: ${error.message}`); report.status = 'failed'; process.exitCode = 1; }
        resolve();
      }));
    }
    try { fs.writeFileSync(path.join(outputDir, 'report.json'), `${JSON.stringify(report, null, 2)}\n`); }
    catch (error) { process.stderr.write(`Could not save report.json: ${error.message}\n`); process.exitCode = 1; }
  }
}

main().catch((error) => {
  process.stderr.write(`FAIL: ${error.message}\n${usage()}\n`);
  process.exitCode = 1;
});
