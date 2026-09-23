import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { compilerRequest, sameSnapshot, serviceUrl } from '../compiler';
import snapshot from '../compiler-snapshot.json';
import { loadConnection, saveConnection } from '../storage';
import { styles } from '../theme';

export default function ConnectionScreen() {
  const [url, setUrl] = useState(''); const [token, setToken] = useState('');
  const [message, setMessage] = useState(''); const [busy, setBusy] = useState(false);
  useEffect(() => { loadConnection().then(value => { setUrl(value.url); setToken(value.token); }).catch(() => setMessage('Could not read the saved connection.')); }, []);
  async function connect() {
    setBusy(true); setMessage('Checking compiler snapshot…');
    try {
      const connection = { url: serviceUrl(url, __DEV__), token: token.trim() };
      const info = await compilerRequest(connection, '/v1/info', __DEV__);
      if (!sameSnapshot(info.compiler, snapshot)) throw new Error('This service uses a different snapshot. Update the app and service together.');
      await saveConnection(connection);
      setMessage(`Connected · compiler ${snapshot.version}`);
    } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }
  return <SafeAreaView style={styles.screen}><KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
    <ScrollView contentContainerStyle={[styles.page, { flex: undefined, flexGrow: 1, gap: 18, paddingBottom: 36 }]} keyboardShouldPersistTaps="handled">
      <View style={styles.header}><Pressable accessibilityRole="button" accessibilityLabel="Back" onPress={() => router.canGoBack() ? router.back() : router.replace('/')} style={styles.iconButton}><Text style={styles.icon}>‹</Text></Pressable><Text style={styles.label}>CONNECTION</Text></View>
      <Text style={styles.heading}>Your compiler.</Text>
      <Text style={styles.body}>Notes stay on this device. Run sends only the current note to this ShipMBLang service. It uses the same compiler snapshot as the desktop app.</Text>
      <Text style={styles.label}>Service URL</Text><TextInput accessibilityLabel="Service URL" style={styles.field} value={url} onChangeText={setUrl} placeholder="https://compiler.example.com" autoCapitalize="none" autoCorrect={false} keyboardType="url" />
      <Text style={styles.label}>Access token</Text><TextInput accessibilityLabel="Access token" style={styles.field} value={token} onChangeText={setToken} placeholder="Your private service token" secureTextEntry autoCapitalize="none" autoCorrect={false} />
      <Pressable accessibilityRole="button" disabled={busy} onPress={connect} style={[styles.button, busy && { opacity: 0.5 }]}><Text style={styles.buttonText}>{busy ? 'Checking…' : 'Connect'}</Text></Pressable>
      {message ? <Text accessibilityLiveRegion="polite" style={styles.body}>{message}</Text> : null}
      <Text style={styles.label}>Compiler {snapshot.version} · {snapshot.commit.slice(0, 7)}</Text>
      <Text style={styles.label}>{Platform.OS === 'web' ? 'Browser preview: the token is kept only for this tab session.' : 'The access token is stored in your device’s secure storage.'}</Text>
    </ScrollView>
  </KeyboardAvoidingView></SafeAreaView>;
}
