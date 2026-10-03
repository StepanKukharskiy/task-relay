import { copyFileSync, mkdirSync, rmSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, resolve } from 'node:path';

const desktop = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const source = resolve(desktop, '..', 'task_relay', 'assets');
const target = join(desktop, 'ui');
// This directory is generated; ship only the current workspace assets.
rmSync(target, {recursive: true, force: true});
mkdirSync(target, { recursive: true });
for (const [from, to] of [
  ['companion.html', 'index.html'],
  ['companion.css', 'companion.css'],
  ['companion.js', 'companion.js'],
  ['companion-setup.js', 'companion-setup.js'],
  ['companion-updates.js', 'companion-updates.js'],
  ['companion-computer.js', 'companion-computer.js'],
  ['companion-workspace.js', 'companion-workspace.js'],
  ['companion-workflow.js', 'companion-workflow.js'],
  ['rich-text.js', 'rich-text.js'],
  ['vendor/marked.umd.js', 'vendor/marked.umd.js'],
  ['vendor/marked.umd.js.LICENSE', 'vendor/marked.umd.js.LICENSE'],
  ['vendor/purify.min.js', 'vendor/purify.min.js'],
  ['vendor/purify.min.js.LICENSE', 'vendor/purify.min.js.LICENSE'],
  ['messages-icon.png', 'messages-icon.png'],
]) { mkdirSync(dirname(join(target,to)),{recursive:true});copyFileSync(join(source, from), join(target, to)); }
console.log('Copied the Task Relay workspace UI.');
