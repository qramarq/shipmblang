import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { NotesProvider } from '../NotesProvider';

export default function Layout() {
  return <SafeAreaProvider><NotesProvider><StatusBar style="dark" />
    <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: '#F7F6F0' } }} />
  </NotesProvider></SafeAreaProvider>;
}
