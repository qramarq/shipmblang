import { router } from 'expo-router';
import { ActivityIndicator, FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNotes } from '../NotesProvider';
import { ink, styles } from '../theme';

export default function Notes() {
  const { notes, ready, loadError, add, saveState, retry } = useNotes();
  return <SafeAreaView style={styles.screen}><View style={styles.page}>
    <View style={styles.header}><View><Text style={styles.label}>SHIPMB</Text><Text style={styles.heading}>Notes</Text></View>
      <Pressable accessibilityRole="button" accessibilityLabel="Compiler connection" onPress={() => router.push('/connection')} style={styles.iconButton}><Text style={styles.icon}>···</Text></Pressable></View>
    {loadError ? <Text accessibilityRole="alert" style={styles.error}>{loadError}</Text> : !ready ? <ActivityIndicator color={ink} /> : <>
      <View style={s.summary}><Pressable onPress={retry}><Text style={styles.label}>{saveState}</Text></Pressable><Text style={styles.label}>{notes.length} {notes.length === 1 ? 'note' : 'notes'}</Text></View>
      <FlatList data={notes} keyExtractor={note => note.id} numColumns={2} columnWrapperStyle={s.columns}
        contentContainerStyle={s.list} keyboardShouldPersistTaps="handled"
        renderItem={({ item }) => <Pressable accessibilityRole="button" accessibilityLabel={item.text.trim() || 'Untitled note'}
          style={[s.card, { backgroundColor: item.color }]} onPress={() => router.push({ pathname: '/note/[id]', params: { id: item.id } })}>
          <Text style={s.cardText} numberOfLines={7}>{item.text || 'An empty page.\nA new possibility.'}</Text>
          <Text style={s.date}>{new Date(item.updatedAt).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</Text>
        </Pressable>}
        ListEmptyComponent={<View style={s.empty}><Text style={s.emptyTitle}>A place for your next idea.</Text><Text style={styles.body}>Write a note in English. Press Run to make it a program.</Text></View>} />
      <Pressable accessibilityRole="button" onPress={() => router.push({ pathname: '/note/[id]', params: { id: add() } })} style={[styles.button, s.new]}><Text style={styles.buttonText}>+ New note</Text></Pressable>
    </>}
  </View></SafeAreaView>;
}
const s = StyleSheet.create({
  summary: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 22 },
  columns: { gap: 14 }, list: { gap: 14, paddingBottom: 24 },
  card: { flex: 1, minHeight: 225, maxWidth: '48%', borderRadius: 4, padding: 18, justifyContent: 'space-between' },
  cardText: { fontSize: 18, lineHeight: 26, color: ink }, date: { fontSize: 11, color: '#62674F', marginTop: 18 },
  new: { marginBottom: 16 }, empty: { marginVertical: 65, gap: 12 },
  emptyTitle: { fontSize: 30, lineHeight: 38, color: ink, letterSpacing: -0.7 },
});
