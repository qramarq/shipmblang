import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { Keyboard, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNotes } from '../../NotesProvider';
import { runNote, terminalText } from '../../compiler';
import snapshot from '../../compiler-snapshot.json';
import { loadConnection } from '../../storage';
import { ink, styles } from '../../theme';

export default function NoteScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { notes, ready, update, remove, saveState, retry } = useNotes();
  const note = notes.find(value => value.id === id);
  const [editing, setEditing] = useState(false);
  const [terminal, setTerminal] = useState(false);
  const [output, setOutput] = useState('Ready when you are.');
  const [busy, setBusy] = useState(false);
  const [menu, setMenu] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [sourceRun, setSourceRun] = useState<string | null>(null);
  const running = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  async function run(mode: 'run' | 'check' = 'run') {
    if (running.current || !note) return;
    if (note.mode === "composition") { router.push({ pathname: "/media/[id]", params: { id } }); return; }
    running.current = true; setBusy(true); setTerminal(true); Keyboard.dismiss();
    const source = note.text; setSourceRun(source); setOutput(mode === 'check' ? 'Checking…' : 'Running…');
    try {
      const connection = await loadConnection();
      if (!connection.url) throw new Error('Connect your ShipMBLang compiler from the ··· menu. Your note stays on this device until you press Check or Run.');
      const result = await runNote(connection, source, snapshot, __DEV__, fetch, mode);
      if (mounted.current) setOutput((mode === 'check' && result.ok ? 'Check passed. Ready to Run; nothing executed.' : terminalText(result)) + '\n\nShipMBLang ' + result.compiler.version + ' · ' + result.compiler.commit.slice(0, 12));
    } catch (error) {
      if (mounted.current) setOutput(error instanceof Error ? error.message : String(error));
    } finally { running.current = false; if (mounted.current) setBusy(false); }
  }
  if (!ready) return <SafeAreaView style={styles.screen}><Text style={styles.body}>Loading notes…</Text></SafeAreaView>;
  if (!note) return <SafeAreaView style={styles.screen}><Pressable onPress={() => router.replace('/')} style={styles.button}><Text style={styles.buttonText}>Back to notes</Text></Pressable></SafeAreaView>;
  return <SafeAreaView style={[styles.screen, { backgroundColor: note.color }]}>
    <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={s.editor}>
      <View style={s.top}><Pressable accessibilityRole="button" accessibilityLabel="Back to notes" onPress={() => router.back()} style={styles.iconButton}><Text style={s.back}>‹</Text></Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="Retry saving note" onPress={retry}><Text style={styles.label}>{saveState}</Text></Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="Note menu" onPress={() => { Keyboard.dismiss(); setMenu(true); }} style={styles.iconButton}><Text style={styles.icon}>···</Text></Pressable></View>
      {!editing && <View style={s.guide}><Text style={s.guideTitle}>Make your words do something.</Text><Text style={s.guideText}>1 Write · 2 Check · 3 Run</Text><Text style={s.guideText}>Write instructions in English. Paragraphs can go in quotes; use Show to print a result.</Text><Pressable accessibilityRole="button" onPress={() => router.push({ pathname: "/media/[id]", params: { id } })}><Text style={s.guideText}>Media & files →</Text></Pressable></View>}
      <TextInput accessibilityLabel="Note program" value={note.text} onChangeText={text => update(id, text)} onFocus={() => { setEditing(true); setTerminal(false); }} onBlur={() => setEditing(false)} multiline
        autoCorrect={false} autoCapitalize="sentences" maxLength={30000} textAlignVertical="top" selectionColor="#B59C48"
        placeholder={'Try: Present "Hello, world!".\n\nThen add your next instruction.'} placeholderTextColor="#65624E" style={s.input} />
      <View style={s.actions}><Pressable accessibilityRole="button" accessibilityLabel="Check note" disabled={busy} onPress={() => run('check')} style={s.checkButton}><Text style={s.terminalLabel}>Check</Text></Pressable><Pressable accessibilityRole="button" accessibilityLabel="Run note" accessibilityState={{ disabled: busy }} disabled={busy} onPress={() => run('run')} style={[styles.button, busy && { opacity: 0.55 }]}><Text style={styles.buttonText}>{busy ? 'Working…' : 'Run'}</Text></Pressable>
        <Pressable accessibilityRole="button" accessibilityState={{ expanded: terminal }} onPress={() => setTerminal(value => !value)} style={s.terminalButton}><Text style={s.terminalLabel}>Terminal {terminal ? '−' : '+'}</Text></Pressable></View>
      {terminal && <View style={s.terminal}><View style={s.terminalHeader}><Text style={s.terminalCaption}>SHIPMBLANG</Text><Text style={s.terminalCaption}>compiler {snapshot.version}</Text></View>
        <ScrollView style={s.outputScroll}>{sourceRun !== null && sourceRun !== note.text && <Text style={s.stale}>Output from the previous text.</Text>}
          <Text selectable accessibilityLiveRegion="polite" style={s.output}>{output}</Text></ScrollView></View>}
    </KeyboardAvoidingView>
    <Modal visible={menu} transparent animationType="fade" onRequestClose={() => { setMenu(false); setConfirmDelete(false); }}>
      <View style={s.overlay}><View style={s.sheet}>
        {confirmDelete ? <><Text style={s.sheetTitle}>Delete this note?</Text><Text style={styles.body}>This removes it from this device.</Text>
          <Pressable accessibilityRole="button" onPress={() => { remove(id); setMenu(false); router.replace('/'); }} style={s.menuItem}><Text style={s.delete}>Delete note</Text></Pressable></> : <>
          <Text style={s.sheetTitle}>This note</Text>
          <Pressable accessibilityRole="button" onPress={() => { setMenu(false); router.push({ pathname: "/media/[id]", params: { id } }); }} style={s.menuItem}><Text style={styles.body}>Media · files, conversion and video</Text></Pressable>
          <Pressable accessibilityRole="button" onPress={() => { setMenu(false); router.push('/connection'); }} style={s.menuItem}><Text style={styles.body}>Compiler connection</Text></Pressable>
          <Pressable accessibilityRole="button" onPress={() => setConfirmDelete(true)} style={s.menuItem}><Text style={s.delete}>Delete note</Text></Pressable></>}
        <Pressable accessibilityRole="button" onPress={() => { setMenu(false); setConfirmDelete(false); }} style={s.menuItem}><Text style={styles.body}>Cancel</Text></Pressable>
      </View></View>
    </Modal>
  </SafeAreaView>;
}
const s = StyleSheet.create({
  editor: { flex: 1, width: '100%', maxWidth: 720, alignSelf: 'center' }, top: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 12 }, back: { fontSize: 36, color: ink },
  guide: { paddingHorizontal: 26, paddingVertical: 12, gap: 6 }, guideTitle: { color: ink, fontSize: 20, fontWeight: '600' }, guideText: { color: '#50513D', fontSize: 13, lineHeight: 19 }, checkButton: { minHeight: 48, paddingHorizontal: 16, justifyContent: 'center', borderWidth: 1, borderColor: '#7B775E', borderRadius: 12 },
  input: { flex: 1, paddingHorizontal: 26, paddingTop: 22, paddingBottom: 12, fontSize: 20, lineHeight: 31, color: ink, minHeight: 100 },
  actions: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 12, gap: 6 },
  terminalButton: { minHeight: 48, justifyContent: 'center', paddingHorizontal: 10 }, terminalLabel: { color: ink, fontSize: 16 },
  terminal: { backgroundColor: '#242B25', paddingHorizontal: 22, paddingTop: 16, paddingBottom: 20, height: 230, maxHeight: '42%' },
  terminalHeader: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 16 }, terminalCaption: { color: '#A2B19D', fontSize: 10, letterSpacing: 1.4 },
  outputScroll: { flex: 1 }, output: { fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace', fontSize: 14, lineHeight: 23, color: '#F5F1D4' }, stale: { color: '#D8C886', fontSize: 12, marginBottom: 10 },
  overlay: { flex: 1, backgroundColor: '#00000055', justifyContent: 'flex-end' }, sheet: { backgroundColor: '#F7F6F0', padding: 26, paddingBottom: 40, borderTopLeftRadius: 22, borderTopRightRadius: 22 },
  sheetTitle: { fontSize: 23, color: ink, marginBottom: 12 }, menuItem: { minHeight: 52, justifyContent: 'center' }, delete: { color: '#9B392D', fontSize: 16 },
});
