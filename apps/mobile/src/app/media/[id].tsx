import { router, useLocalSearchParams } from 'expo-router';
import { randomUUID, digestStringAsync, CryptoDigestAlgorithm } from 'expo-crypto';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Image, Pressable, ScrollView, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNotes } from '../../NotesProvider';
import { compilerRequest, sameSnapshot } from '../../compiler';
import snapshot from '../../compiler-snapshot.json';
import { loadConnection } from '../../storage';
import { activeJob, conversionSource, compositionSource, mediaPath, submitMedia, titleSource, type MediaAsset, type MediaJob } from '../../media';
import { downloadMedia, pickMedia, releaseMedia, saveMedia, uploadMedia } from '../../mediaFiles';
import { MediaPlayer } from '../../MediaPlayer';
import { styles } from '../../theme';

export default function MediaScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { notes, update, add, setMode, saveState } = useNotes();
  const note = notes.find(n => n.id === id);
  const [assets, setAssets] = useState<MediaAsset[]>([]);
  const [job, setJob] = useState<MediaJob | null>(null);
  const [message, setMessage] = useState('Files upload only when you choose Add media.');
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<{uri: string; name: string} | null>(null);
  const [stale, setStale] = useState(false);
  const pending = useRef<{key: string; requestId: string} | null>(null);
  const mode = note?.mode || 'program';
  const guard = async (action: () => Promise<void>) => {
    setBusy(true);
    try { await action(); } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  };
  const refresh = useCallback(async () => {
    const connection = await loadConnection();
    if (!connection.url) throw new Error('Connect your private compiler service first.');
    const value = await compilerRequest(connection, mediaPath(id), __DEV__);
    if (!sameSnapshot(value.compiler, snapshot)) throw new Error('Compiler snapshot mismatch. Update app and service together.');
    setAssets(value.assets); setJob(value.job); if (value.job) setMessage('');
  }, [id]);
  useEffect(() => { Promise.resolve().then(refresh).catch(error => setMessage(error.message)); }, [refresh]);
  useEffect(() => {
    if (!activeJob(job)) return;
    const timer = setInterval(() => { refresh().catch(error => setMessage('Connection interrupted. Reconnect to see the same job: ' + error.message)); }, 1200);
    return () => clearInterval(timer);
  }, [job, refresh]);
  useEffect(() => {
    let current = true;
    if (note && job) digestStringAsync(CryptoDigestAlgorithm.SHA256, note.text).then(hash => { if (current) setStale(hash !== job.source_revision); });
    return () => { current = false; };
  }, [note, job]);
  useEffect(() => () => { if (preview) void releaseMedia(preview.uri).catch(() => {}); }, [preview]);
  async function run(check: boolean) {
    if (!note) return;
    const key = JSON.stringify([id, note.text, mode, check]);
    if (pending.current?.key !== key) pending.current = { key, requestId: randomUUID() };
    await guard(async () => {
      const result = await submitMedia(await loadConnection(), id, note.text, mode, pending.current!.requestId, check);
      setJob(result); setMessage(check ? 'Checking…' : 'Job started. You can keep writing.');
      pending.current = null;
    });
  }
  async function play(path: string, name: string) {
    await guard(async () => { setMessage('Downloading for playback…'); const uri = await downloadMedia(await loadConnection(), path, name); setPreview({uri, name}); setMessage('Ready to play.'); });
  }
  async function starter(source: string, target: 'program' | 'composition', asset?: MediaAsset) {
    await guard(async () => {
      const newId = add(source, target);
      if (asset) await compilerRequest(await loadConnection(), mediaPath(newId) + '/copy-assets', __DEV__, { project: id, asset_id: asset.id });
      router.replace({ pathname: '/media/[id]', params: { id: newId } });
    });
  }
  if (!note) return <SafeAreaView style={styles.screen}><Text style={styles.body}>Open a saved note to use media.</Text></SafeAreaView>;
  return <SafeAreaView style={styles.screen}><ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ padding: 22, gap: 14, width: '100%', maxWidth: 720, alignSelf: 'center', paddingBottom: 40 }}>
    <View style={styles.header}><Pressable accessibilityRole="button" onPress={() => router.back()}><Text style={styles.body}>‹ Note</Text></Pressable><Text style={styles.label}>{saveState}</Text></View>
    <Text style={styles.heading}>Make it move.</Text><Text style={styles.body}>Bring a clip, convert it, or write a little film. Media runs on your connected computer; playback happens here.</Text>
    <View style={{flexDirection:'row', flexWrap:'wrap', gap:8}}>{(['program','composition'] as const).map(value => <Pressable key={value} accessibilityRole="button" onPress={() => setMode(id, value)} style={[styles.button, {opacity: mode === value ? 1 : .65}]}><Text style={styles.buttonText}>{value === 'program' ? 'Program' : 'Video composition'}</Text></Pressable>)}</View>
    <TextInput accessibilityLabel="Media program" multiline value={note.text} onChangeText={text => update(id,text)} style={[styles.field, {minHeight:200, textAlignVertical:'top', lineHeight:25}]} />
    <View style={{flexDirection:'row', flexWrap:'wrap', gap:8}}>
      <Pressable accessibilityRole="button" disabled={busy || activeJob(job)} onPress={() => run(true)} style={styles.button}><Text style={styles.buttonText}>Check</Text></Pressable>
      <Pressable accessibilityRole="button" disabled={busy || activeJob(job)} onPress={() => run(false)} style={styles.button}><Text style={styles.buttonText}>Run</Text></Pressable>
      {activeJob(job) && <Pressable accessibilityRole="button" onPress={() => guard(async () => { setJob(await compilerRequest(await loadConnection(), mediaPath(id) + '/jobs/' + job!.id + '/cancel', __DEV__, {})); })} style={styles.button}><Text style={styles.buttonText}>Stop</Text></Pressable>}
      <Pressable accessibilityRole="button" onPress={() => guard(refresh)} style={styles.iconButton}><Text style={styles.body}>Refresh</Text></Pressable>
    </View>
    <Text accessibilityLiveRegion="polite" style={styles.body}>{message}</Text>
    {job && <View style={[styles.field,{gap:8}]}><Text style={styles.body}>{stale ? 'Earlier text · ' : ''}{job.message}</Text><Text style={styles.label}>{job.phase} · compiler {snapshot.version}</Text>
      {job.progress?.out_time && <Text style={styles.label}>Processed {job.progress.out_time} · {job.progress.speed}</Text>}
      {job.stdout ? <Text selectable style={styles.body}>{job.stdout}</Text> : null}
      {job.diagnostics.map((d,i) => <Text key={i} style={styles.error}>{d.message}{d.span ? ` (characters ${d.span.start}–${d.span.end})` : ''}</Text>)}
      {job.outputs.map(output => <View key={output.id}><Text style={styles.body}>{output.name} · {output.duration || '?'} s</Text><Pressable accessibilityRole="button" onPress={() => play(mediaPath(id) + '/jobs/' + job.id + '/outputs/' + output.id, output.name)} style={styles.button}><Text style={styles.buttonText}>Download and play</Text></Pressable></View>)}
    </View>}
    {preview && <><View>{/\.(png|jpe?g)$/i.test(preview.name) ? <Image accessibilityLabel={preview.name} source={{uri: preview.uri}} resizeMode="contain" style={{width:"100%", height:220}}/> : <MediaPlayer key={preview.uri} uri={preview.uri}/>}</View><Pressable accessibilityRole="button" onPress={() => guard(() => saveMedia(preview.uri, preview.name))} style={styles.button}><Text style={styles.buttonText}>Save / share result</Text></Pressable></>}
    <Pressable accessibilityRole="button" disabled={busy || activeJob(job)} onPress={() => guard(async () => { const connection = await loadConnection(); const archive = await compilerRequest(connection, mediaPath(id) + '/archives', __DEV__, { source: note.text }); const uri = await downloadMedia(connection, mediaPath(id) + '/archives/' + archive.id, archive.name); try { await saveMedia(uri, archive.name); } finally { setTimeout(() => { void releaseMedia(uri).catch(() => {}); }, 10000); } })} style={styles.button}><Text style={styles.buttonText}>Export note + media</Text></Pressable>
    <Text style={[styles.heading,{fontSize:24}]}>Media for this note</Text>
    <Pressable accessibilityRole="button" disabled={busy} onPress={async () => { try { const asset = await pickMedia(); if (asset) await guard(async () => { setMessage('Uploading selected file…'); await uploadMedia(await loadConnection(), id, asset); await refresh(); setMessage('Imported. Choose a starter below.'); }); } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); } }} style={styles.button}><Text style={styles.buttonText}>Add media · upload a copy</Text></Pressable>
    {assets.map(asset => <View key={asset.id} style={[styles.field,{gap:8}]}><Text style={styles.body}>{asset.name}</Text><Text selectable style={styles.label}>{asset.path}</Text><Pressable accessibilityRole="button" onPress={() => starter(conversionSource(asset),'program',asset)}><Text style={styles.body}>New conversion note →</Text></Pressable><Pressable accessibilityRole="button" onPress={() => starter(compositionSource(asset),'composition',asset)}><Text style={styles.body}>New composition note →</Text></Pressable><Pressable accessibilityRole="button" onPress={() => play(mediaPath(id)+'/assets/'+asset.id,asset.name)}><Text style={styles.body}>Play on this device</Text></Pressable></View>)}
    <Pressable accessibilityRole="button" onPress={() => starter(titleSource,'composition')} style={styles.button}><Text style={styles.buttonText}>New title-card note</Text></Pressable>
    <Pressable accessibilityRole="button" onPress={() => guard(async () => { const setup = await compilerRequest(await loadConnection(), '/v1/media/setup', __DEV__); setMessage(['conversion','playback','rendering'].map(key => `${key}: ${setup[key] ? 'ready' : 'needs setup'}`).join('\n') + '\n' + setup.help); })}><Text style={styles.body}>Media setup</Text></Pressable>
    <Pressable accessibilityRole="button" onPress={() => router.push('/connection')}><Text style={styles.body}>Compiler connection</Text></Pressable>
  </ScrollView></SafeAreaView>;
}
