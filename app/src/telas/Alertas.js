import { useCallback, useEffect, useState } from 'react';
import { Alert, FlatList, Linking, RefreshControl, Text, TouchableOpacity, View } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { supabase } from '../supabase';
import { abrirConfigFlutuante, testarNotificacao } from '../notificacoes';
import { cores, s } from '../estilo';

export default function Alertas({ userId }) {
  const [lista, setLista] = useState([]);
  const [carregando, setCarregando] = useState(false);
  const [mostrarDica, setMostrarDica] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem('dica_flutuante_ok').then((v) => setMostrarDica(v !== '1')).catch(() => setMostrarDica(true));
  }, []);

  function esconderDica() {
    setMostrarDica(false);
    AsyncStorage.setItem('dica_flutuante_ok', '1').catch(() => {});
  }

  async function teste() {
    try {
      await testarNotificacao();
      Alert.alert('Teste agendado', 'Saia do app agora (va para a tela inicial). Em 5 segundos a notificacao deve aparecer flutuando em cima da tela.');
    } catch (e) {
      Alert.alert('Teste', 'Nao consegui criar a notificacao: ' + e.message);
    }
  }

  const carregar = useCallback(async () => {
    setCarregando(true);
    const { data } = await supabase.from('alerts').select('*')
      .order('created_at', { ascending: false }).limit(50);
    setLista(data ?? []);
    setCarregando(false);
  }, []);

  useEffect(() => {
    carregar();
    const canal = supabase.channel('alertas-' + userId)
      .on('postgres_changes',
        { event: 'INSERT', schema: 'public', table: 'alerts', filter: `user_id=eq.${userId}` },
        (p) => setLista((l) => [p.new, ...l].slice(0, 50)))
      .subscribe();
    return () => { supabase.removeChannel(canal); };
  }, [userId, carregar]);

  function limpar() {
    Alert.alert('Apagar historico', 'Apagar todos os alertas?', [
      { text: 'Cancelar', style: 'cancel' },
      { text: 'Apagar', style: 'destructive', onPress: async () => {
        await supabase.from('alerts').delete().eq('user_id', userId);
        setLista([]);
      } },
    ]);
  }

  return (
    <FlatList
      style={s.tela}
      contentContainerStyle={{ padding: 16 }}
      data={lista}
      keyExtractor={(a) => String(a.id)}
      refreshControl={<RefreshControl refreshing={carregando} onRefresh={carregar} tintColor={cores.destaque} />}
      ListHeaderComponent={mostrarDica ? (
        <View style={[s.cartao, { borderColor: cores.destaque }]}>
          <Text style={[s.valor, { fontWeight: '700', marginBottom: 6 }]}>Notificacao flutuante</Text>
          <Text style={{ color: cores.fraco, lineHeight: 20 }}>
            Para o alerta aparecer em cima da tela (mesmo com o Roblox ou outro app aberto), ligue
            "Flutuante", "Pop-up" ou "Mostrar na tela" na notificacao "Alertas do jogo".
          </Text>
          <TouchableOpacity style={s.botao} onPress={() => abrirConfigFlutuante().catch(() => {})}>
            <Text style={s.botaoTexto}>Ativar notificacao flutuante</Text>
          </TouchableOpacity>
          <TouchableOpacity style={s.botaoSec} onPress={teste}>
            <Text style={s.botaoSecTexto}>Testar (aparece em 5 segundos)</Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={esconderDica} style={{ alignItems: 'center', marginTop: 10 }}>
            <Text style={{ color: cores.fraco }}>Ja ativei, esconder</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <TouchableOpacity onPress={() => setMostrarDica(true)} style={{ alignItems: 'flex-end', marginBottom: 8 }}>
          <Text style={{ color: cores.fraco, fontSize: 12 }}>Notificacao flutuante</Text>
        </TouchableOpacity>
      )}
      ListEmptyComponent={<Text style={s.vazio}>Nenhum alerta ainda. Quando o PC detectar uma mensagem, ela aparece aqui.</Text>}
      ListFooterComponent={lista.length ? (
        <TouchableOpacity style={s.botaoSec} onPress={limpar}>
          <Text style={s.botaoSecTexto}>Apagar historico</Text>
        </TouchableOpacity>) : null}
      renderItem={({ item: a }) => (
        <View style={[s.cartao, a.teste && { opacity: 0.6 }]}>
          <Text style={{ color: cores.destaque, fontWeight: '800', fontSize: 16 }}>
            {a.teste ? 'Teste' : (a.frase || 'Mensagem detectada')}
          </Text>
          <Text style={{ color: cores.fraco, fontSize: 12 }}>
            {new Date(a.created_at).toLocaleString('pt-BR')}
          </Text>
          {a.mensagem ? (<><Text style={s.rotulo}>Mensagem</Text><Text style={s.valor}>{a.mensagem}</Text></>) : null}
          <Text style={s.rotulo}>Jogador</Text>
          <Text style={s.valor}>{a.jogador || '-'}</Text>
          {a.mapa ? (<><Text style={s.rotulo}>Mapa</Text><Text style={s.valor}>{a.mapa}</Text></>) : null}
          {a.codigo_servidor ? (<>
            <Text style={s.rotulo}>Codigo do servidor</Text>
            <Text style={[s.valor, { fontFamily: 'monospace', fontSize: 13 }]} selectable>{a.codigo_servidor}</Text>
          </>) : null}
          {a.link ? (
            <TouchableOpacity style={[s.botao, { marginTop: 12 }]} onPress={() => Linking.openURL(a.link)}>
              <Text style={s.botaoTexto}>Entrar no servidor</Text>
            </TouchableOpacity>
          ) : null}
        </View>
      )}
    />
  );
}
