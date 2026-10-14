import { useEvent } from 'expo';
import { useVideoPlayer, VideoView } from 'expo-video';
import { Pressable, Text, View } from 'react-native';
import { styles } from './theme';

export function MediaPlayer({ uri }: { uri: string }) {
  const player = useVideoPlayer(uri);
  const { isPlaying } = useEvent(player, 'playingChange', { isPlaying: player.playing });
  const { error } = useEvent(player, 'statusChange', { status: player.status });
  return <View><VideoView player={player} nativeControls style={{ height: 220, width: '100%', backgroundColor: '#17231C', borderRadius: 12 }} />
    <Pressable accessibilityRole="button" onPress={() => isPlaying ? player.pause() : player.play()} style={[styles.button,{marginVertical:8}]}><Text style={styles.buttonText}>{isPlaying ? "Pause preview" : "Play preview"}</Text></Pressable>
    {error && <Text style={styles.error}>{error.message}</Text>}
    <Text style={styles.label}>Play on this device · downloaded result</Text></View>;
}
