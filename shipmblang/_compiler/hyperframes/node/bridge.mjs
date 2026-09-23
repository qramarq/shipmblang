import fs from 'node:fs/promises';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

// SDK progress goes to stderr; stdout is one JSON result for the Python caller.
console.log = (...args) => console.error(...args);
const report = value => process.stdout.write(JSON.stringify(value));
const probe = file => JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-show_streams', '-show_format', '-of', 'json', file], { encoding: 'utf8', timeout: 30000, windowsHide: true }));

try {
  const [project, output] = process.argv.slice(2);
  const { composition: spec } = JSON.parse(await fs.readFile(path.join(project, 'shipmb.json'), 'utf8'));
  const { lintHyperframeHtml } = await import('@hyperframes/lint');
  const html = await fs.readFile(path.join(project, 'index.html'), 'utf8');
  const lint = await lintHyperframeHtml(html);
  const errors = lint.findings.filter(item => item.severity === 'error');
  if (errors.length) throw new Error(`HyperFrames lint failed: ${JSON.stringify(errors)}`);
  for (const element of spec.elements.filter(e => e.kind === 'audio' || e.kind === 'video')) {
    const parts = element.value.replaceAll('\\', '/').split('/').pop().split('.');
    const ext = parts.pop().toLowerCase();
    const file = path.join(project, 'assets', `${element.id}.${parts.length && /^[a-z0-9]{1,10}$/.test(ext) ? ext : 'bin'}`);
    const media = probe(file);
    const stream = media.streams.find(s => s.codec_type === element.kind);
    if (!stream) throw new Error(`Missing ${element.kind} stream for ${element.name}`);
    const duration = Number(stream.duration ?? media.format.duration);
    if (!Number.isFinite(duration) || duration + 1 / spec.fps < element.duration / spec.fps)
      throw new Error(`Media ${element.name} is shorter than its authored duration.`);
  }
  const { createRenderJob, executeRenderJob } = await import('@hyperframes/producer');
  const job = createRenderJob({ fps: spec.fps, quality: 'standard', format: 'mp4', strictness: 'strict' });
  await executeRenderJob(job, project, output, (current, message) => console.error(`${Math.round(current.progress)}% ${message}`));
  const media = probe(output);
  const video = media.streams.find(s => s.codec_type === 'video');
  const [num, den] = (video?.avg_frame_rate ?? '0/1').split('/').map(Number);
  const duration = Number(media.format.duration);
  if (!video || video.width !== spec.width || video.height !== spec.height || Math.abs(num / den - spec.fps) > 0.01 || Math.abs(duration - spec.duration / spec.fps) > Math.max(0.15, 2 / spec.fps))
    throw new Error('Rendered video dimensions, frame rate, or duration do not match the composition.');
  if (spec.elements.some(e => e.kind === 'audio') && !media.streams.some(s => s.codec_type === 'audio'))
    throw new Error('Rendered output is missing its audio stream.');
  report({ status: 'rendered', media });
} catch (error) {
  report({ status: 'error', error: error.message });
  process.exitCode = 1;
}
