import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';
import type { Connection } from './compiler';

const CONNECTION_KEY = 'shipmb.connection.v1';
let webToken = '';
export async function loadConnection(): Promise<Connection> {
  const url = await AsyncStorage.getItem(CONNECTION_KEY) || '';
  const token = Platform.OS === 'web' ? webToken : await SecureStore.getItemAsync(CONNECTION_KEY) || '';
  return { url, token };
}
export async function saveConnection(connection: Connection) {
  if (Platform.OS === 'web') webToken = connection.token;
  else await SecureStore.setItemAsync(CONNECTION_KEY, connection.token);
  await AsyncStorage.setItem(CONNECTION_KEY, connection.url);
}
