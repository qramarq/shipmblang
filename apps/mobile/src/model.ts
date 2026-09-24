export type Note = { mode?: "program" | "composition"; id: string; text: string; color: string; createdAt: string; updatedAt: string };
export const colors = ['#FFEDAA', '#DCEBDD', '#F5DED8', '#DFE6F4'];
export function createNote(id: string, count: number, now = new Date().toISOString()): Note {
  return { id, text: '', color: colors[count % colors.length], createdAt: now, updatedAt: now };
}
export function decodeNotes(raw: string | null): Note[] {
  if (!raw) return [];
  const value: unknown = JSON.parse(raw);
  if (!Array.isArray(value) || value.some((n: Note) => !n ||
      (n.mode !== undefined && n.mode !== 'program' && n.mode !== 'composition') || typeof n.id !== 'string' || typeof n.text !== 'string' || !colors.includes(n.color) ||
      typeof n.createdAt !== 'string' || typeof n.updatedAt !== 'string') ||
      new Set(value.map((n: Note) => n.id)).size !== value.length) {
    throw new Error('Saved notes could not be read. Your stored data has not been replaced.');
  }
  return value;
}
export function noteTitle(note: Note) { return note.text.trim().split('\n')[0] || 'Untitled note'; }
export function createWriter(write: (value: string) => Promise<void>) {
  let pending = Promise.resolve();
  return (notes: Note[]) => {
    const snapshot = JSON.stringify(notes);
    pending = pending.catch(() => {}).then(() => write(snapshot));
    return pending;
  };
}
