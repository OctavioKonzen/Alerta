import { Linking, Platform } from 'react-native';
import * as Notifications from 'expo-notifications';
import * as Device from 'expo-device';
import Constants from 'expo-constants';
import { supabase } from './supabase';

// Mostra a notificacao mesmo com o app aberto.
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

let tokenAtual = null;

export async function registrarCelular() {
  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync('alertas', {
      name: 'Alertas do jogo',
      importance: Notifications.AndroidImportance.MAX,
      vibrationPattern: [0, 600, 300, 600, 300, 600],
      lightColor: '#E53935',
      sound: 'default',
      lockscreenVisibility: Notifications.AndroidNotificationVisibility.PUBLIC,
      bypassDnd: true,
    });
  }
  if (!Device.isDevice) {
    throw new Error('Notificacoes so funcionam em um celular de verdade.');
  }
  let { status } = await Notifications.getPermissionsAsync();
  if (status !== 'granted') {
    ({ status } = await Notifications.requestPermissionsAsync());
  }
  if (status !== 'granted') {
    throw new Error('Permita as notificacoes do app nas configuracoes do celular.');
  }
  const projectId = Constants.expoConfig?.extra?.eas?.projectId;
  const { data: token } = await Notifications.getExpoPushTokenAsync({ projectId });
  const { error } = await supabase.rpc('registrar_token', { p_token: token });
  if (error) throw new Error(error.message);
  tokenAtual = token;
  return token;
}

export async function desregistrarCelular() {
  if (tokenAtual) {
    await supabase.from('push_tokens').delete().eq('token', tokenAtual);
    tokenAtual = null;
  }
}

// Tocar na notificacao abre o servidor no Roblox (se tiver link).
export function ouvirToques() {
  const abrir = (resp) => {
    const link = resp?.notification?.request?.content?.data?.link;
    if (link) Linking.openURL(link).catch(() => {});
  };
  Notifications.getLastNotificationResponseAsync().then(abrir);
  const sub = Notifications.addNotificationResponseReceivedListener(abrir);
  return () => sub.remove();
}
