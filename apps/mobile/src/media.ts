import { compilerRequest, type Connection } from './compiler';
import snapshot from './compiler-snapshot.json';

export type MediaAsset = { id: string; name: string; path: string; size: number };
export type MediaOutput = { id: string; name: string; size: number; duration?: string };
export type MediaJob = { id: string; state: string; phase: string; message: string; source_revision: string;
  stdout?: string; outputs: MediaOutput[]; diagnostics: {message: string; span?: {start: number; end: number}}[];
  progress?: {out_time?: string; speed?: string} };
export type MediaMode = 'program' | 'composition';
export const mediaPath = (id: string) => '/v1/media/projects/' + encodeURIComponent(id);
export const activeJob = (job: MediaJob | null) => !!job && !['completed', 'failed', 'cancelled'].includes(job.state);
export function submitMedia(connection: Connection, id: string, source: string, mode: MediaMode, requestId: string, check: boolean) {
  return compilerRequest(connection, mediaPath(id) + '/jobs', __DEV__, { source, mode, request_id: requestId, check, compiler: snapshot }) as Promise<MediaJob>;
}
export function conversionSource(asset: MediaAsset) {
  return `Let source be "${asset.path}".\nLet destination be "outputs/converted.mp4".\nRun FFmpeg:\nInput clip from source.\nOutput result to destination.\nOutput option "-c:v" for result with "libx264".\nOutput option "-c:a" for result with "aac".\nEnd FFmpeg.`;
}
export const titleSource = `Create a video at 640 by 360 pixels and 24 frames per second.
Add scene "intro" lasting 1 seconds.
Set the background of scene "intro" to "#24362b".
Show text "My first little film" as "title" in scene "intro".
Place "title" at 320 by 180 pixels.
Set the font size of "title" to 36 pixels.
Set the color of "title" to "#fff6ce".
Fade in "title" over 0.25 seconds.`;

export function compositionSource(asset: MediaAsset) {
  const ext = asset.path.split('.').pop()?.toLowerCase() || '';
  const kind = ['png','jpg','jpeg'].includes(ext) ? 'image' : ['wav','mp3','m4a','ogg'].includes(ext) ? 'audio' : 'video';
  return `Create a video at 640 by 360 pixels and 24 frames per second.
Add scene "intro" lasting 1 seconds.
Set the background of scene "intro" to "#24362b".
${kind === 'audio' ? 'Play' : 'Show'} ${kind} "${asset.path}" as "media" in scene "intro" lasting 1 seconds.
${kind !== 'audio' ? 'Place "media" at 320 by 180 pixels.\nSet the size of "media" to 640 by 360 pixels.\n' : ''}Show text "Made with my media" as "title" in scene "intro".
Place "title" at 320 by 50 pixels.
Set the font size of "title" to 28 pixels.
Set the color of "title" to "#ffffff".`;
}
