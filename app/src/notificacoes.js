import { Linking, Platform } from 'react-native';
import * as Notifications from 'expo-notifications';
import * as Device from 'expo-device';
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

// Canal com importancia MAXIMA: e o que permite a notificacao flutuante (aparece em cima da tela).
export async function criarCanal() {
  if (Platform.OS !== 'android') return;
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

// Abre a tela do celular onde a pessoa liga "Flutuante" / "Pop-up" para este canal.
export async function abrirConfigFlutuante() {
  await criarCanal();
  try {
    const IntentLauncher = require('expo-intent-launcher');
    await IntentLauncher.startActivityAsync('android.settings.CHANNEL_NOTIFICATION_SETTINGS', {
      extra: {
        'android.provider.extra.APP_PACKAGE': 'com.octaviokonzen.alerta',
        'android.provider.extra.CHANNEL_ID': 'alertas',
      },
    });
  } catch {
    await Linking.openSettings();
  }
}

// Notificacao de teste em 5 segundos (de para minimizar o app e ver se ela flutua).
export async function testarNotificacao() {
  await criarCanal();
  await Notifications.scheduleNotificationAsync({
    content: {
      title: 'Teste de notificacao flutuante',
      body: 'Se apareceu em cima da tela, esta tudo certo!',
      sound: 'default',
      priority: Notifications.AndroidNotificationPriority.MAX,
    },
    trigger: {
      type: Notifications.SchedulableTriggerInputTypes.TIME_INTERVAL,
      seconds: 5,
      channelId: 'alertas',
    },
  });
}

export async function registrarCelular() {
  await criarCanal();
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
  // Token do Firebase (FCM) deste celular; a nuvem manda o push direto por ele.
  const { data: token } = await Notifications.getDevicePushTokenAsync();
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
    const req = resp?.notification?.request;
    const link = req?.content?.data?.link || req?.trigger?.remoteMessage?.data?.link;
    if (link) Linking.openURL(link).catch(() => {});
  };
  Notifications.getLastNotificationResponseAsync().then(abrir);
  const sub = Notifications.addNotificationResponseReceivedListener(abrir);
  return () => sub.remove();
}
