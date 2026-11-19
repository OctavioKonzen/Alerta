import { useCallback, useEffect, useState } from 'react';
import { Alert, FlatList, Linking, RefreshControl, Text, TouchableOpacity, View } from 'react-native';
import { supabase } from '../supabase';
import { cores, s } from '../estilo';

export default function Alertas({ userId }) {
  const [lista, setLista] = useState([]);
  const [carregando, setCarregando] = useState(false);

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
          <Text style={s.rotulo}>Codigo do servidor (Job ID)</Text>
          <Text style={[s.valor, { fontFamily: 'monospace', fontSize: 13 }]} selectable>{a.job_id || '-'}</Text>
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
