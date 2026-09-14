import { copyFileSync, mkdirSync, rmSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, resolve } from 'node:path';

const desktop = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const source = resolve(desktop, '..', 'task_relay', 'assets');
const target = join(desktop, 'ui');
// This directory is generated; obsolete workspace assets must not ship in the companion.
rmSync(target, {recursive: true, force: true});
mkdirSync(target, { recursive: true });
for (const [from, to] of [
  ['companion.html', 'index.html'],
  ['companion.css', 'companion.css'],
  ['companion.js', 'companion.js'],
  ['companion-setup.js', 'companion-setup.js'],
  ['companion-updates.js', 'companion-updates.js'],
  ['messages-icon.png', 'messages-icon.png'],
]) copyFileSync(join(source, from), join(target, to));
console.log('Copied the minimal Task Relay companion UI.');
