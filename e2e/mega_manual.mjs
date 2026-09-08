// Navegador MANUAL (sin headless) para operar MEGA a mano.
// Uso:  node mega_manual.mjs
// - Abre una ventana real de Chromium (perfil persistente en /tmp/mega_profile).
// - No cierra solo: haz TÚ las acciones y cierra la ventana al terminar.
// - La sesión queda guardada en /tmp/mega_profile para reutilizarla después.
import { chromium } from '@playwright/test';
import fs from 'node:fs';

const PROFILE = '/tmp/mega_profile';
try {
  fs.rmSync(PROFILE + '.ready', { force: true });
} catch {}

const browser = await chromium.launchPersistentContext(PROFILE, {
  headless: false,
  viewport: null, // tamaño natural de la ventana
  args: ['--start-maximized', '--ozone-platform-hint=auto'],
});

let page = browser.pages()[0] || (await browser.newPage());
page.setDefaultTimeout(60000);
await page.goto('https://mega.nz', { waitUntil: 'domcontentloaded', timeout: 90000 }).catch(() => {});
await page.waitForTimeout(3000);

fs.writeFileSync(PROFILE + '.ready', String(process.pid));
console.log('VENTANA ABIERTA en mega.nz (perfil: ' + PROFILE + ').');
console.log('Cuando termines, cierra la ventana del navegador.');

browser.on('close', () => {
  console.log('BROWSER CERRADO. Perfil conservado en ' + PROFILE);
  process.exit(0);
});

// Mantener vivo el proceso
setInterval(() => {}, 1 << 30);
