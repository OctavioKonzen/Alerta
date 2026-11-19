import { useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Text, TextInput, TouchableOpacity } from 'react-native';
import { supabase } from '../supabase';
import { cores, s } from '../estilo';

export default function Login() {
  const [email, setEmail] = useState('');
  const [senha, setSenha] = useState('');
  const [carregando, setCarregando] = useState(false);
  const [msg, setMsg] = useState(null);

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
