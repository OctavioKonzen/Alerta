// Atualizacao automatica do app: ao abrir, confere se ha versao nova na
// Release "ultima" do GitHub, baixa o APK sozinho e abre o instalador.
// (Fora da Play Store o Android sempre pede para a pessoa tocar em "Instalar".)
import { useEffect, useState } from 'react';
import { ActivityIndicator, Modal, Platform, Text, TouchableOpacity, View } from 'react-native';
import Constants from 'expo-constants';
import * as FileSystem from 'expo-file-system';
import * as IntentLauncher from 'expo-intent-launcher';
import { cores, s } from './estilo';

const ORIGEM_OK = 'https://github.com/OctavioKonzen/Alerta/releases/download/ultima/';
const URL_VERSAO = `${ORIGEM_OK}versao-app.json`;

async function abrirInstalador(arquivo) {
  const uri = await FileSystem.getContentUriAsync(arquivo);
  await IntentLauncher.startActivityAsync('android.intent.action.VIEW', {
    data: uri,
    flags: 1, // FLAG_GRANT_READ_URI_PERMISSION
    type: 'application/vnd.android.package-archive',
  });
}

export default function Atualizacao() {
  const [nova, setNova] = useState(null);       // { versao, url }
  const [progresso, setProgresso] = useState(0);
  const [arquivo, setArquivo] = useState(null);
  const [erro, setErro] = useState(null);
  const [fechado, setFechado] = useState(false);

  useEffect(() => {
    if (Platform.OS !== 'android') return;
    const atual = Number(Constants.expoConfig?.android?.versionCode ?? 0);
    let cancelado = false;
    (async () => {
      try {
        const r = await fetch(`${URL_VERSAO}?t=${Date.now()}`);
        if (!r.ok) return;
        const info = await r.json();
        if (!(Number(info.codigo) > atual) || !String(info.url).startsWith(ORIGEM_OK)) return;
        if (cancelado) return;
        setNova(info);

        const destino = `${FileSystem.cacheDirectory}AlertaRoblox-${info.versao}.apk`;
        const ja = await FileSystem.getInfoAsync(destino);
        if (!ja.exists) {
          // Baixa num arquivo temporario e so troca o nome quando terminar inteiro.
          const parcial = `${destino}.parcial`;
          await FileSystem.deleteAsync(parcial, { idempotent: true });
          let esperado = 0;
          const download = FileSystem.createDownloadResumable(info.url, parcial, {}, (p) => {
            if (p.totalBytesExpectedToWrite > 0) {
              esperado = p.totalBytesExpectedToWrite;
              setProgresso(p.totalBytesWritten / p.totalBytesExpectedToWrite);
            }
          });
          const r = await download.downloadAsync();
          const feito = await FileSystem.getInfoAsync(parcial);
          if (!r || r.status !== 200 || !feito.exists || feito.size < 1_000_000 || (esperado && feito.size !== esperado)) {
            await FileSystem.deleteAsync(parcial, { idempotent: true });
            throw new Error('download incompleto');
          }
          await FileSystem.moveAsync({ from: parcial, to: destino });
        }
        if (cancelado) return;
        setArquivo(destino);
        setProgresso(1);
        // Nao abre o instalador sozinho: a pessoa toca em "Instalar agora".
      } catch (e) {
        if (!cancelado) setErro('Nao consegui baixar a atualizacao. Tente de novo mais tarde.');
      }
    })();
    return () => { cancelado = true; };
  }, []);

  if (!nova || fechado) return null;

  return (
    <Modal transparent animationType="fade" visible onRequestClose={() => setFechado(true)}>
      <View style={{ flex: 1, backgroundColor: '#000b', justifyContent: 'center', padding: 24 }}>
        <View style={[s.cartao, { padding: 20, borderColor: cores.destaque }]}>
          <Text style={[s.titulo, { fontSize: 20 }]}>Atualizacao disponivel</Text>
          <Text style={{ color: cores.fraco, marginBottom: 16 }}>Versao {nova.versao}</Text>

          {erro ? <Text style={s.erro}>{erro}</Text> : arquivo ? (
            <Text style={{ color: cores.texto, lineHeight: 20 }}>
              Pronto! Toque em "Instalar agora" e depois em "Instalar" na tela do Android.{'\n'}
              Se o Android pedir, permita instalar apps desta fonte.
            </Text>
          ) : (
            <>
              <Text style={{ color: cores.texto, marginBottom: 10 }}>
                Baixando... {Math.round(progresso * 100)}%
              </Text>
              <View style={{ height: 8, backgroundColor: cores.borda, borderRadius: 4, overflow: 'hidden' }}>
                <View style={{ height: 8, width: `${Math.round(progresso * 100)}%`, backgroundColor: cores.destaque }} />
              </View>
              <ActivityIndicator color={cores.destaque} style={{ marginTop: 14 }} />
            </>
          )}

          {arquivo ? (
            <TouchableOpacity style={s.botao} onPress={() => abrirInstalador(arquivo)
              .catch(() => setErro('Nao consegui abrir o instalador. Baixe pelo site: octaviokonzen.github.io/Alerta'))}>
              <Text style={s.botaoTexto}>Instalar agora</Text>
            </TouchableOpacity>
          ) : null}
          <TouchableOpacity style={s.botaoSec} onPress={() => setFechado(true)}>
            <Text style={s.botaoSecTexto}>Depois</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}
