import * as Picker from 'expo-document-picker';
import * as FileSystem from 'expo-file-system/legacy';
import * as Sharing from 'expo-sharing';
import { Platform } from 'react-native';
import { serviceUrl, type Connection } from './compiler';
import { mediaPath, type MediaAsset } from './media';

export async function pickMedia() {
  const picked = await Picker.getDocumentAsync({ type: ['video/*', 'audio/*', 'image/*'], copyToCacheDirectory: true, multiple: false });
  if (picked.canceled) return null;
  const asset = picked.assets[0];
  if (!asset.size || asset.size > 100 * 1024 * 1024) throw new Error('Choose a media file below 100 MiB.');
  return asset;
}
export async function uploadMedia(connection: Connection, id: string, asset: Picker.DocumentPickerAsset): Promise<MediaAsset> {
  const url = serviceUrl(connection.url, __DEV__) + mediaPath(id) + '/assets?name=' + encodeURIComponent(asset.name);
  const headers = { Authorization: 'Bearer ' + connection.token, 'Content-Type': 'application/octet-stream' };
  if (!connection.token) throw new Error('Connect the compiler first.');
  if (Platform.OS === 'web') {
    if (!asset.file) throw new Error('The selected browser file is unavailable. Choose it again.');
    const response = await fetch(url, { method: 'POST', headers, body: asset.file, redirect: 'error' });
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || 'Upload failed.');
    return value;
  }
  const response = await FileSystem.uploadAsync(url, asset.uri, { headers, httpMethod: 'POST', uploadType: FileSystem.FileSystemUploadType.BINARY_CONTENT });
  const value = JSON.parse(response.body);
  if (response.status !== 201) throw new Error(value.error || 'Upload failed.');
  return value;
}
export async function downloadMedia(connection: Connection, path: string, name: string) {
  const url = serviceUrl(connection.url, __DEV__) + path;
  const headers = { Authorization: 'Bearer ' + connection.token };
  if (Platform.OS === 'web') {
    const response = await fetch(url, { headers, redirect: 'error' });
    if (!response.ok) throw new Error('Download failed. Reconnect and retry.');
    if (Number(response.headers.get('content-length')) > 100 * 1024 * 1024) {
      await response.body?.cancel();
      throw new Error('Browser downloads are limited to 100 MiB. Export larger results from the desktop app.');
    }
    return URL.createObjectURL(await response.blob());
  }
  const directory = FileSystem.cacheDirectory + 'shipmb-media/';
  await FileSystem.makeDirectoryAsync(directory, { intermediates: true });
  const result = await FileSystem.downloadAsync(url, directory + Date.now() + '-' + name.replace(/[^a-zA-Z0-9._-]/g, '_'), { headers });
  if (result.status !== 200) throw new Error('Download failed. Reconnect and retry.');
  return result.uri;
}
export async function saveMedia(uri: string, name: string) {
  if (Platform.OS === 'web') {
    const link = document.createElement('a'); link.href = uri; link.download = name; link.click();
  } else {
    if (!await Sharing.isAvailableAsync()) throw new Error('Sharing is unavailable on this device.');
    await Sharing.shareAsync(uri);
  }
}

export async function releaseMedia(uri: string) {
  if (Platform.OS === 'web') URL.revokeObjectURL(uri);
  else if (FileSystem.cacheDirectory && uri.startsWith(FileSystem.cacheDirectory + 'shipmb-media/'))
    await FileSystem.deleteAsync(uri, { idempotent: true });
}
