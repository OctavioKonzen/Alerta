import { useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Text, TextInput, TouchableOpacity } from 'react-native';
import * as WebBrowser from 'expo-web-browser';
import Constants from 'expo-constants';
import { supabase } from '../supabase';
import { cores, s } from '../estilo';

export default function Login() {
  const [email, setEmail] = useState('');
  const [senha, setSenha] = useState('');
  const [carregando, setCarregando] = useState(false);
  const [msg, setMsg] = useState(null);

  async function entrarDiscord() {
    setCarregando(true); setMsg(null);
    try {
      const funcao = Constants.expoConfig.extra.funcaoDiscord || 'discord-bot';
      const { data, error } = await supabase.functions.invoke(funcao, { body: { acao: 'app_login_iniciar' } });
      if (error || !data?.url) throw new Error('Nao consegui falar com a nuvem. Tente de novo.');
      const r = await WebBrowser.openAuthSessionAsync(data.url, 'alertaroblox://login');
      if (r.type === 'success') {
        const erro = r.url.match(/[?&]erro=([^&]*)/);
        if (erro) throw new Error(decodeURIComponent(erro[1].replace(/\+/g, ' ')));
        const token = r.url.match(/[?&]token_hash=([^&]+)/);
        if (!token) throw new Error('O Discord nao devolveu o login. Tente de novo.');
        const { error: e2 } = await supabase.auth.verifyOtp({ token_hash: decodeURIComponent(token[1]), type: 'magiclink' });
        if (e2) throw new Error(traduzir(e2.message));
      }
    } catch (e) {
      setMsg({ erro: true, texto: e.message });
    }
    setCarregando(false);
  }

  async function entrar() {
    setCarregando(true); setMsg(null);
    const { error } = await supabase.auth.signInWithPassword({ email: email.trim(), password: senha });
    if (error) setMsg({ erro: true, texto: traduzir(error.message) });
    setCarregando(false);
  }

  async function criarConta() {
    if (senha.length < 8) return setMsg({ erro: true, texto: 'A senha precisa ter pelo menos 8 caracteres.' });
    setCarregando(true); setMsg(null);
    const { data, error } = await supabase.auth.signUp({ email: email.trim(), password: senha });
    if (error) setMsg({ erro: true, texto: traduzir(error.message) });
    else if (!data.session) setMsg({ erro: false, texto: 'Conta criada! Confirme pelo link que enviamos no seu e-mail e depois entre aqui.' });
    setCarregando(false);
  }

  return (
    <KeyboardAvoidingView style={s.centro} behavior="padding">
      <Text style={s.titulo}>Alerta Roblox</Text>
      <Text style={s.sub}>Receba no celular as mensagens do jogo detectadas no seu PC.</Text>
      {msg && <Text style={msg.erro ? s.erro : { color: cores.ok, marginBottom: 12 }}>{msg.texto}</Text>}
      {!carregando && (
        <TouchableOpacity style={[s.botao, { backgroundColor: '#5865F2', marginBottom: 6 }]} onPress={entrarDiscord}>
          <Text style={s.botaoTexto}>Entrar com Discord</Text>
        </TouchableOpacity>
      )}
      <Text style={{ color: cores.fraco, textAlign: 'center', marginVertical: 14 }}>ou use e-mail e senha</Text>
      <TextInput style={s.input} placeholder="E-mail" placeholderTextColor={cores.fraco}
        autoCapitalize="none" keyboardType="email-address" value={email} onChangeText={setEmail} />
      <TextInput style={s.input} placeholder="Senha" placeholderTextColor={cores.fraco}
        secureTextEntry value={senha} onChangeText={setSenha} />
      {carregando ? <ActivityIndicator color={cores.destaque} style={{ marginTop: 12 }} /> : (
        <>
          <TouchableOpacity style={s.botao} onPress={entrar}>
            <Text style={s.botaoTexto}>Entrar</Text>
          </TouchableOpacity>
          <TouchableOpacity style={s.botaoSec} onPress={criarConta}>
            <Text style={s.botaoSecTexto}>Criar conta</Text>
          </TouchableOpacity>
        </>
      )}
    </KeyboardAvoidingView>
  );
}

function traduzir(m) {
  if (/invalid login/i.test(m)) return 'E-mail ou senha incorretos.';
  if (/not confirmed/i.test(m)) return 'Confirme seu e-mail antes de entrar.';
  if (/already registered/i.test(m)) return 'Este e-mail ja tem conta. Use "Entrar".';
  if (/rate limit/i.test(m)) return 'Muitas tentativas. Espere um pouco.';
  return m;
}
