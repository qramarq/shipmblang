import AsyncStorage from '@react-native-async-storage/async-storage';
import { randomUUID } from 'expo-crypto';
import React, { createContext, useContext, useEffect, useRef, useState } from 'react';
import { createNote, createWriter, decodeNotes, type Note } from './model';

const KEY = 'shipmb.notes.v1';
type NotesContext = { notes: Note[]; ready: boolean; loadError: string; saveState: string;
  add: (source?: string, mode?: "program" | "composition") => string; setMode: (id: string, mode: "program" | "composition") => void; update: (id: string, text: string) => void; remove: (id: string) => void; retry: () => void };
const Context = createContext<NotesContext | null>(null);
export function NotesProvider({ children }: { children: React.ReactNode }) {
  const [notes, setNotes] = useState<Note[]>([]);
  const [ready, setReady] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [saveState, setSaveState] = useState('Saved on device');
  const current = useRef(notes);
  const revision = useRef(0);
  const writer = useRef(createWriter(value => AsyncStorage.setItem(KEY, value)));
  useEffect(() => {
    AsyncStorage.getItem(KEY).then(decodeNotes).then(value => {
      current.current = value; setNotes(value); setReady(true);
    }).catch(error => setLoadError(String(error.message || error)));
  }, []);
  function persist(value: Note[]) {
    const turn = ++revision.current;
    current.current = value; setNotes(value); setSaveState('Saving…');
    writer.current(value).then(() => {
      if (turn === revision.current) setSaveState('Saved on device');
    }).catch(() => { if (turn === revision.current) setSaveState('Not saved · tap to retry'); });
  }
  return <Context.Provider value={{ notes, ready, loadError, saveState,
    add: (source = '', mode = 'program') => { const note = { ...createNote(randomUUID(), current.current.length), text: source, mode }; persist([note, ...current.current]); return note.id; },
    setMode: (id, mode) => persist(current.current.map(note => note.id === id ? { ...note, mode } : note)),
    update: (id, text) => persist(current.current.map(note => note.id === id ? { ...note, text, updatedAt: new Date().toISOString() } : note)),
    remove: id => persist(current.current.filter(note => note.id !== id)),
    retry: () => persist(current.current),
  }}>{children}</Context.Provider>;
}
export function useNotes() {
  const value = useContext(Context);
  if (!value) throw new Error('NotesProvider is missing.');
  return value;
}
