import { router } from 'expo-router';
import { ActivityIndicator, FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNotes } from '../NotesProvider';
import starters from '../starters.json';
import snapshot from '../compiler-snapshot.json';
import { titleSource } from '../media';
import { ink, styles } from '../theme';

export default function Notes() {
  const { notes, ready, loadError, add, saveState, retry } = useNotes();
  return <SafeAreaView style={styles.screen}><View style={styles.page}>
    <View style={styles.header}><View><Text style={styles.label}>SHIPMB</Text><Text style={styles.heading}>Little programs.</Text></View>
      <Pressable accessibilityRole="button" accessibilityLabel="Compiler connection" onPress={() => router.push('/connection')} style={styles.iconButton}><Text style={styles.icon}>···</Text></Pressable></View>
    {loadError ? <Text accessibilityRole="alert" style={styles.error}>{loadError}</Text> : !ready ? <ActivityIndicator color={ink} /> : <>
      <FlatList data={notes} keyExtractor={note => note.id} numColumns={2} columnWrapperStyle={s.columns}
        ListHeaderComponent={<><View style={s.intro}><Text style={s.introTitle}>What would you like to make?</Text><Text style={styles.body}>Start with a few words. Check your instructions, then Run when you’re ready.</Text><Text style={styles.label}>ShipMBLang {snapshot.version}</Text></View>
      <View style={s.starters}>{starters.map(starter => <Pressable key={starter.title} accessibilityRole="button" onPress={() => router.push({ pathname: "/note/[id]", params: { id: add(starter.source) } })} style={s.starter}><Text style={s.starterTitle}>{starter.title}  ↗</Text><Text style={s.starterHint}>{starter.hint}</Text></Pressable>)}<Pressable accessibilityRole="button" onPress={() => router.push({ pathname: "/media/[id]", params: { id: add(titleSource, "composition") } })} style={s.starter}><Text style={s.starterTitle}>Make a little film  ↗</Text><Text style={s.starterHint}>Write a title card, then render and play it.</Text></Pressable></View>
      <View style={s.summary}><Pressable onPress={retry}><Text style={styles.label}>{saveState}</Text></Pressable><Text style={styles.label}>{notes.length} {notes.length === 1 ? 'note' : 'notes'}</Text></View></>}
        contentContainerStyle={s.list} keyboardShouldPersistTaps="handled"
        renderItem={({ item }) => <Pressable accessibilityRole="button" accessibilityLabel={item.text.trim() || 'Untitled note'}
          style={[s.card, { backgroundColor: item.color }]} onPress={() => router.push({ pathname: '/note/[id]', params: { id: item.id } })}>
          <Text style={s.cardText} numberOfLines={7}>{item.text || 'An empty page.\nA new possibility.'}</Text>
          <Text style={s.date}>{new Date(item.updatedAt).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</Text>
        </Pressable>}
        ListEmptyComponent={<View style={s.empty}><Text style={s.emptyTitle}>Your notes live here.</Text><Text style={styles.body}>Choose a starter above or write a blank note. Nothing runs until you ask.</Text></View>} />
      <Pressable accessibilityRole="button" onPress={() => router.push({ pathname: '/note/[id]', params: { id: add() } })} style={[styles.button, s.new]}><Text style={styles.buttonText}>+ New note</Text></Pressable>
    </>}
  </View></SafeAreaView>;
}
const s = StyleSheet.create({
  intro: { gap: 8, marginBottom: 18 }, introTitle: { color: ink, fontSize: 22, fontWeight: '600' },
  starters: { gap: 8, marginBottom: 20 }, starter: { padding: 14, borderRadius: 14, backgroundColor: '#FFFFFF', borderWidth: 1, borderColor: '#DFE3D9' }, starterTitle: { fontSize: 16, fontWeight: '600', color: ink }, starterHint: { fontSize: 13, lineHeight: 19, color: '#50594C', marginTop: 3 },
  summary: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 22 },
  columns: { gap: 14 }, list: { gap: 14, paddingBottom: 24 },
  card: { flex: 1, minHeight: 180, maxWidth: '48%', borderRadius: 16, padding: 18, justifyContent: 'space-between' },
  cardText: { fontSize: 17, lineHeight: 25, color: ink }, date: { fontSize: 11, color: '#62674F', marginTop: 18 },
  new: { marginBottom: 16 }, empty: { marginVertical: 12, gap: 12 },
  emptyTitle: { fontSize: 23, lineHeight: 30, color: ink, letterSpacing: -0.7 },
});
