import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator, Alert, FlatList, Image, Linking, Modal, RefreshControl,
  Text, TouchableOpacity, View,
} from 'react-native';
import * as WebBrowser from 'expo-web-browser';
import Constants from 'expo-constants';
import { supabase } from '../supabase';
import { cores, s } from '../estilo';

const FUNCAO = Constants.expoConfig.extra.funcaoDiscord || 'discord-bot';
const VOLTAR = 'alertaroblox://discord';

async function chamar(acao, extra = {}) {
  const { data, error } = await supabase.functions.invoke(FUNCAO, { body: { acao, ...extra } });
  if (error) throw new Error('Nao consegui falar com a nuvem. Tente de novo.');
  if (data?.erro) throw new Error(data.erro);
  return data;
}

export default function Discord() {
  const [painel, setPainel] = useState(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState(null);
  const [servidor, setServidor] = useState(null); // servidor escolhendo canal
  const [canais, setCanais] = useState(null);
  const [ocupado, setOcupado] = useState(false);

  const carregar = useCallback(async () => {
    setCarregando(true);
    try { setPainel(await chamar('painel')); setErro(null); }
    catch (e) { setErro(e.message); }
    setCarregando(false);
  }, []);

  useEffect(() => { carregar(); }, [carregar]);

  async function conectar() {
    setOcupado(true);
    try {
      const { url } = await chamar('iniciar');
      const r = await WebBrowser.openAuthSessionAsync(url, VOLTAR);
      if (r.type === 'success') {
        const m = r.url.match(/[?&]erro=([^&]*)/);
        const erroLogin = m ? decodeURIComponent(m[1].replace(/\+/g, ' ')) : null;
        if (erroLogin) Alert.alert('Discord', erroLogin);
      }
      await carregar();
    } catch (e) { Alert.alert('Discord', e.message); }
    setOcupado(false);
  }

  function desconectar() {
    Alert.alert('Desconectar Discord', 'Os alertas vao parar de chegar em todos os canais do Discord.', [
      { text: 'Cancelar', style: 'cancel' },
      { text: 'Desconectar', style: 'destructive', onPress: async () => {
        try { await chamar('sair'); } catch (e) { Alert.alert('Discord', e.message); }
        carregar();
      } },
    ]);
  }

  async function abrirCanais(g) {
    setServidor(g); setCanais(null);
    try { setCanais((await chamar('canais', { guild_id: g.id })).canais); }
    catch (e) { setServidor(null); Alert.alert('Discord', e.message); }
  }

  async function escolher(c) {
    setOcupado(true);
    try {
      await chamar('escolher', { guild_id: servidor.id, channel_id: c.id });
      setServidor(null);
      Alert.alert('Pronto!', `Os alertas vao chegar em #${c.nome}. O bot mandou uma mensagem de teste la.`);
      carregar();
    } catch (e) { Alert.alert('Discord', e.message); }
    setOcupado(false);
  }

  async function participar(g) {
    try {
      await chamar('participar', { guild_id: g.id });
      Alert.alert('Pronto!', `Seus alertas vao para #${g.canal.nome}.`);
    } catch (e) { Alert.alert('Discord', e.message); }
    carregar();
  }

  function parar(g) {
    Alert.alert('Parar meus alertas', `Seus alertas nao vao mais para "${g.nome}".`, [
      { text: 'Cancelar', style: 'cancel' },
      { text: 'Parar', style: 'destructive', onPress: async () => {
        try { await chamar('remover', { guild_id: g.id }); } catch (e) { Alert.alert('Discord', e.message); }
        carregar();
      } },
    ]);
  }

  function desligar(g) {
    Alert.alert('Desligar canal', `Desligar o canal de alertas de "${g.nome}"? Para os alertas de TODOS os membros.`, [
      { text: 'Cancelar', style: 'cancel' },
      { text: 'Desligar', style: 'destructive', onPress: async () => {
        try { await chamar('desligar', { guild_id: g.id }); } catch (e) { Alert.alert('Discord', e.message); }
        carregar();
      } },
    ]);
  }

  const convite = painel?.convite ? (
    <TouchableOpacity style={s.botaoSec} onPress={() => Linking.openURL(painel.convite)}>
      <Text style={s.botaoSecTexto}>Adicionar o bot a um servidor</Text>
    </TouchableOpacity>
  ) : null;

  if (!painel) {
    return (
      <View style={[s.tela, { padding: 16 }]}>
        {erro ? (
          <>
            <Text style={s.erro}>{erro}</Text>
            <TouchableOpacity style={s.botaoSec} onPress={carregar}>
              <Text style={s.botaoSecTexto}>Tentar de novo</Text>
            </TouchableOpacity>
          </>
        ) : <ActivityIndicator color={cores.destaque} style={{ marginTop: 40 }} />}
      </View>
    );
  }

  if (!painel.conectado) {
    return (
      <View style={[s.tela, { padding: 16 }]}>
        <View style={[s.cartao, { borderColor: cores.destaque }]}>
          <Text style={[s.valor, { fontWeight: '700', marginBottom: 6 }]}>Alertas no Discord</Text>
          <Text style={{ color: cores.fraco, lineHeight: 20 }}>
            Conecte sua conta do Discord. Depois, nos servidores onde o bot estiver e voce for
            administrador, escolha o canal que recebe os alertas.
          </Text>
          <TouchableOpacity style={s.botao} onPress={conectar} disabled={ocupado}>
            {ocupado ? <ActivityIndicator color="#fff" /> : <Text style={s.botaoTexto}>Conectar com Discord</Text>}
          </TouchableOpacity>
          {convite}
        </View>
      </View>
    );
  }

  return (
    <>
      <FlatList
        style={s.tela}
        contentContainerStyle={{ padding: 16 }}
        data={painel.servidores}
        keyExtractor={(g) => g.id}
        refreshControl={<RefreshControl refreshing={carregando} onRefresh={carregar} tintColor={cores.destaque} />}
        ListHeaderComponent={
          <View style={[s.cartao, { borderColor: cores.destaque }]}>
            <Text style={s.rotulo}>Discord conectado</Text>
            <Text style={[s.valor, { fontWeight: '700' }]}>{painel.nome}</Text>
            {erro ? <Text style={[s.erro, { marginTop: 8 }]}>{erro}</Text> : null}
            {convite}
            <TouchableOpacity style={s.botaoSec} onPress={desconectar}>
              <Text style={[s.botaoSecTexto, { color: '#ff6b6b' }]}>Desconectar Discord</Text>
            </TouchableOpacity>
          </View>
        }
        ListEmptyComponent={
          <Text style={s.vazio}>
            O bot ainda nao esta em nenhum servidor seu. Toque em "Adicionar o bot a um servidor"
            e depois puxe esta tela para baixo para atualizar.
          </Text>
        }
        renderItem={({ item: g }) => (
          <View style={s.cartao}>
            <View style={{ flexDirection: 'row', alignItems: 'center' }}>
              {g.icone
                ? <Image source={{ uri: g.icone }} style={{ width: 36, height: 36, borderRadius: 18, marginRight: 10 }} />
                : <View style={{ width: 36, height: 36, borderRadius: 18, marginRight: 10, backgroundColor: cores.borda }} />}
              <Text style={[s.valor, { fontWeight: '700', flex: 1 }]}>{g.nome}</Text>
            </View>
            <Text style={s.rotulo}>Canal dos alertas</Text>
            <Text style={[s.valor, { color: g.canal && g.participando ? cores.ok : cores.fraco }]}>
              {g.canal && g.participando ? `Seus alertas vao para #${g.canal.nome}`
                : g.canal ? `#${g.canal.nome} (seus alertas nao vao para la)`
                : g.admin ? 'Nenhum canal escolhido' : 'Esperando um administrador escolher o canal'}
            </Text>
            {g.canal ? (g.participando ? (
              <TouchableOpacity style={s.botaoSec} onPress={() => parar(g)}>
                <Text style={[s.botaoSecTexto, { color: '#ff6b6b' }]}>Parar meus alertas</Text>
              </TouchableOpacity>
            ) : (
              <TouchableOpacity style={s.botao} onPress={() => participar(g)}>
                <Text style={s.botaoTexto}>Mandar meus alertas aqui</Text>
              </TouchableOpacity>
            )) : null}
            {g.admin ? (
              <>
                <Text style={[s.rotulo, { marginTop: 12 }]}>Administrador</Text>
                <TouchableOpacity style={g.canal ? s.botaoSec : s.botao} onPress={() => abrirCanais(g)}>
                  <Text style={g.canal ? s.botaoSecTexto : s.botaoTexto}>{g.canal ? 'Trocar canal' : 'Escolher canal'}</Text>
                </TouchableOpacity>
                {g.canal ? (
                  <TouchableOpacity style={s.botaoSec} onPress={() => desligar(g)}>
                    <Text style={[s.botaoSecTexto, { color: '#ff6b6b' }]}>Desligar canal</Text>
                  </TouchableOpacity>
                ) : null}
              </>
            ) : null}
          </View>
        )}
      />

      <Modal visible={!!servidor} transparent animationType="slide" onRequestClose={() => setServidor(null)}>
        <View style={{ flex: 1, backgroundColor: '#000a', justifyContent: 'flex-end' }}>
          <View style={[s.cartao, { maxHeight: '75%', borderRadius: 16, margin: 0 }]}>
            <Text style={[s.valor, { fontWeight: '700', marginBottom: 8 }]}>
              Canal em "{servidor?.nome}"
            </Text>
            {!canais || ocupado ? <ActivityIndicator color={cores.destaque} style={{ margin: 24 }} /> : (
              <FlatList
                data={canais}
                keyExtractor={(c) => c.id}
                ListEmptyComponent={<Text style={s.vazio}>O bot nao ve nenhum canal de texto aqui.</Text>}
                renderItem={({ item: c }) => (
                  <TouchableOpacity onPress={() => escolher(c)}
                    style={{ paddingVertical: 14, borderBottomColor: cores.borda, borderBottomWidth: 1 }}>
                    <Text style={s.valor}># {c.nome}</Text>
                  </TouchableOpacity>
                )}
              />
            )}
            <TouchableOpacity style={s.botaoSec} onPress={() => setServidor(null)}>
              <Text style={s.botaoSecTexto}>Cancelar</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </>
  );
}
