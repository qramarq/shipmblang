import { StyleSheet } from 'react-native';
export const ink = '#2F392F';
export const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: '#F7F6F0' },
  page: { flex: 1, width: '100%', maxWidth: 680, alignSelf: 'center', paddingHorizontal: 22 },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: 16, gap: 12 },
  heading: { fontSize: 34, fontWeight: '600', letterSpacing: -1.5, color: ink },
  label: { color: '#6E756B', fontSize: 13, letterSpacing: 0.3 },
  iconButton: { minWidth: 44, minHeight: 44, alignItems: 'center', justifyContent: 'center', borderRadius: 24 },
  icon: { color: ink, fontSize: 25 },
  button: { minHeight: 48, borderRadius: 12, backgroundColor: ink, paddingHorizontal: 22, alignItems: 'center', justifyContent: 'center' },
  buttonText: { color: '#FFFBEA', fontSize: 16, fontWeight: '600' },
  body: { color: ink, fontSize: 16, lineHeight: 24 },
  field: { borderWidth: 1, borderColor: '#D2D6CD', borderRadius: 12, padding: 14, fontSize: 16, color: ink, backgroundColor: '#FFFFFF', minHeight: 50 },
  error: { color: '#9B392D', fontSize: 14, lineHeight: 21 },
});
