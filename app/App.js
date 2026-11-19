import { useEffect, useState } from 'react';
import { ActivityIndicator, StatusBar as RNStatusBar, Text, TouchableOpacity, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { supabase } from './src/supabase';
import { desregistrarCelular, ouvirToques, registrarCelular } from './src/notificacoes';
import { cores, s } from './src/estilo';
import Login from './src/telas/Login';
import Alertas from './src/telas/Alertas';
import Pcs from './src/telas/Pcs';
import Discord from './src/telas/Discord';
import Atualizacao from './src/Atualizacao';

export default function App() {
  return <><Principal /><Atualizacao /></>;
}

function Principal() {
  const [sessao, setSessao] = useState(undefined);
  const [aba, setAba] = useState('alertas');
  const [aviso, setAviso] = useState(null);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setSessao(data.session));
    const { data: sub } = supabase.auth.onAuthStateChange((_e, sess) => setSessao(sess));
    const pararToques = ouvirToques();
    return () => { sub.subscription.unsubscribe(); pararToques(); };
  }, []);

  const userId = sessao?.user?.id;
  useEffect(() => {
    if (!userId) return;
    registrarCelular().then(() => setAviso(null)).catch((e) => setAviso(e.message));
  }, [userId]);

  async function sair() {
    await desregistrarCelular();
    await supabase.auth.signOut();
  }

  if (sessao === undefined) {
    return <View style={s.centro}><ActivityIndicator color={cores.destaque} /></View>;
  }
  if (!sessao) {
    return <><StatusBar style="light" /><Login /></>;
  }

  return (
    <View style={[s.tela, { paddingTop: RNStatusBar.currentHeight ?? 24 }]}>
      <StatusBar style="light" />
      <View style={{ flexDirection: 'row', alignItems: 'center', padding: 16, paddingBottom: 8 }}>
        <Text style={[s.titulo, { flex: 1, fontSize: 22, marginBottom: 0 }]}>Alerta Roblox</Text>
        <TouchableOpacity onPress={sair}><Text style={{ color: cores.fraco }}>Sair</Text></TouchableOpacity>
      </View>
      <Text style={{ color: cores.fraco, paddingHorizontal: 16, fontSize: 12 }}>{sessao.user.email}</Text>
      {aviso && <Text style={[s.erro, { paddingHorizontal: 16, marginTop: 8 }]}>{aviso}</Text>}

      <View style={{ flex: 1 }}>
        {aba === 'alertas' ? <Alertas userId={userId} /> : aba === 'pcs' ? <Pcs /> : <Discord />}
      </View>

      <View style={{ flexDirection: 'row', borderTopColor: cores.borda, borderTopWidth: 1 }}>
        {[['alertas', 'Alertas'], ['pcs', 'Meus PCs'], ['discord', 'Discord']].map(([id, nome]) => (
          <TouchableOpacity key={id} onPress={() => setAba(id)}
            style={{ flex: 1, padding: 16, alignItems: 'center' }}>
            <Text style={{ color: aba === id ? cores.destaque : cores.fraco, fontWeight: '700' }}>{nome}</Text>
          </TouchableOpacity>
        ))}
      </View>
    </View>
  );
}
