import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator, Alert, FlatList, RefreshControl, Text, TextInput, TouchableOpacity, View,
} from 'react-native';
import { supabase } from '../supabase';
import { cores, s } from '../estilo';

// Frases que o PC procura no chat do Roblox. Ficam na conta: valem para todos os PCs.
export default function Frases({ userId }) {
  const [lista, setLista] = useState([]);
  const [carregando, setCarregando] = useState(false);
  const [nova, setNova] = useState('');
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState(null);

  const carregar = useCallback(async () => {
    setCarregando(true);
    const { data, error } = await supabase.rpc('minhas_frases');
    if (error) setErro('Nao consegui carregar as frases.');
    else { setLista(data ?? []); setErro(null); }
    setCarregando(false);
  }, []);

  useEffect(() => { carregar(); }, [carregar]);

  async function adicionar() {
    const texto = nova.trim();
    if (texto.length < 3) return setErro('A frase precisa ter pelo menos 3 letras.');
    setSalvando(true); setErro(null);
    const { error } = await supabase.from('frases').insert({ user_id: userId, texto });
    if (error) setErro(/limite/i.test(error.message) ? 'Limite de 30 frases.' : 'Nao consegui salvar a frase.');
    else { setNova(''); await carregar(); }
    setSalvando(false);
  }

  function remover(f) {
    Alert.alert('Remover frase', `Parar de procurar "${f.texto}"?`, [
      { text: 'Cancelar', style: 'cancel' },
      { text: 'Remover', style: 'destructive', onPress: async () => {
        await supabase.from('frases').delete().eq('id', f.id);
        carregar();
      } },
    ]);
  }

  return (
    <FlatList
      style={s.tela}
      contentContainerStyle={{ padding: 16 }}
      data={lista}
      keyExtractor={(f) => f.id}
      keyboardShouldPersistTaps="handled"
      refreshControl={<RefreshControl refreshing={carregando} onRefresh={carregar} tintColor={cores.destaque} />}
      ListHeaderComponent={
        <View style={[s.cartao, { borderColor: cores.destaque }]}>
          <Text style={[s.valor, { fontWeight: '700', marginBottom: 6 }]}>Frases procuradas</Text>
          <Text style={{ color: cores.fraco, lineHeight: 20, marginBottom: 12 }}>
            Quando uma destas aparecer no chat do Roblox, voce recebe o alerta. Vale para todos os seus PCs
            (eles atualizam sozinhos em ate 1 minuto). Maiusculas e pontuacao nao importam.
          </Text>
          <TextInput style={[s.input, { marginBottom: 8 }]} placeholder="Ex.: Something feels off"
            placeholderTextColor={cores.fraco} value={nova} onChangeText={setNova}
            onSubmitEditing={adicionar} returnKeyType="done" maxLength={120} />
          {erro ? <Text style={s.erro}>{erro}</Text> : null}
          <TouchableOpacity style={s.botao} onPress={adicionar} disabled={salvando}>
            {salvando ? <ActivityIndicator color="#fff" /> : <Text style={s.botaoTexto}>+ Adicionar frase</Text>}
          </TouchableOpacity>
        </View>
      }
      ListEmptyComponent={carregando ? null : (
        <Text style={s.vazio}>Nenhuma frase. Adicione uma acima para o PC comecar a procurar.</Text>
      )}
      renderItem={({ item: f }) => (
        <View style={[s.cartao, { flexDirection: 'row', alignItems: 'center' }]}>
          <Text style={[s.valor, { flex: 1 }]}>{f.texto}</Text>
          <TouchableOpacity onPress={() => remover(f)} style={{ paddingHorizontal: 10, paddingVertical: 6 }}>
            <Text style={{ color: '#ff6b6b', fontWeight: '700' }}>Remover</Text>
          </TouchableOpacity>
        </View>
      )}
    />
  );
}
