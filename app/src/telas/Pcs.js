import { useCallback, useEffect, useState } from 'react';
import { Alert, FlatList, RefreshControl, Text, TouchableOpacity, View } from 'react-native';
import { supabase } from '../supabase';
import { cores, s } from '../estilo';

export default function Pcs() {
  const [lista, setLista] = useState([]);
  const [carregando, setCarregando] = useState(false);

  const carregar = useCallback(async () => {
    setCarregando(true);
    const { data } = await supabase.from('pc_keys')
      .select('id, nome, prefixo, created_at, last_used_at').order('created_at');
    setLista(data ?? []);
    setCarregando(false);
  }, []);

  useEffect(() => { carregar(); }, [carregar]);

  function remover(pc) {
    Alert.alert('Remover PC', `"${pc.nome}" vai parar de mandar alertas para esta conta.`, [
      { text: 'Cancelar', style: 'cancel' },
      { text: 'Remover', style: 'destructive', onPress: async () => {
        await supabase.from('pc_keys').delete().eq('id', pc.id);
        carregar();
      } },
    ]);
  }

  return (
    <FlatList
      style={s.tela}
      contentContainerStyle={{ padding: 16 }}
      data={lista}
      keyExtractor={(p) => p.id}
      refreshControl={<RefreshControl refreshing={carregando} onRefresh={carregar} tintColor={cores.destaque} />}
      ListHeaderComponent={
        <View style={[s.cartao, { borderColor: cores.destaque }]}>
          <Text style={[s.valor, { fontWeight: '700', marginBottom: 6 }]}>Como ligar um PC</Text>
          <Text style={{ color: cores.fraco, lineHeight: 20 }}>
            1. Aqui no app, na aba Discord, toque em "Conectar com Discord".{'\n'}
            2. No PC, instale e abra o Alerta Roblox e clique em "Conectar com Discord".{'\n'}
            Use a mesma conta do Discord nos dois. Ate 5 PCs por conta.
          </Text>
        </View>
      }
      ListEmptyComponent={<Text style={s.vazio}>Nenhum PC ligado ainda.</Text>}
      renderItem={({ item: pc }) => (
        <View style={s.cartao}>
          <Text style={[s.valor, { fontWeight: '700' }]}>{pc.nome}</Text>
          <Text style={s.rotulo}>Chave: {pc.prefixo}...</Text>
          <Text style={s.rotulo}>
            Ultimo alerta: {pc.last_used_at ? new Date(pc.last_used_at).toLocaleString('pt-BR') : 'nunca'}
          </Text>
          <TouchableOpacity style={s.botaoSec} onPress={() => remover(pc)}>
            <Text style={[s.botaoSecTexto, { color: '#ff6b6b' }]}>Remover</Text>
          </TouchableOpacity>
        </View>
      )}
    />
  );
}
