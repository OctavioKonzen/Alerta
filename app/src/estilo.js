import { StyleSheet } from 'react-native';

export const cores = {
  fundo: '#0f1115',
  cartao: '#1a1d24',
  borda: '#2a2f3a',
  texto: '#f2f4f8',
  fraco: '#8b93a3',
  destaque: '#E53935',
  ok: '#43A047',
};

export const s = StyleSheet.create({
  tela: { flex: 1, backgroundColor: cores.fundo },
  centro: { flex: 1, justifyContent: 'center', padding: 24, backgroundColor: cores.fundo },
  titulo: { color: cores.texto, fontSize: 28, fontWeight: '800', marginBottom: 6 },
  sub: { color: cores.fraco, fontSize: 14, marginBottom: 24 },
  input: {
    backgroundColor: cores.cartao, color: cores.texto, borderColor: cores.borda,
    borderWidth: 1, borderRadius: 10, padding: 14, fontSize: 16, marginBottom: 12,
  },
  botao: {
    backgroundColor: cores.destaque, borderRadius: 10, padding: 14,
    alignItems: 'center', marginTop: 4,
  },
  botaoTexto: { color: '#fff', fontSize: 16, fontWeight: '700' },
  botaoSec: {
    borderColor: cores.borda, borderWidth: 1, borderRadius: 10, padding: 12,
    alignItems: 'center', marginTop: 10,
  },
  botaoSecTexto: { color: cores.texto, fontSize: 15, fontWeight: '600' },
  cartao: {
    backgroundColor: cores.cartao, borderRadius: 12, padding: 14, marginBottom: 10,
    borderColor: cores.borda, borderWidth: 1,
  },
  rotulo: { color: cores.fraco, fontSize: 12, marginTop: 6 },
  valor: { color: cores.texto, fontSize: 15 },
  vazio: { color: cores.fraco, textAlign: 'center', marginTop: 40, paddingHorizontal: 24 },
  erro: { color: '#ff6b6b', marginBottom: 12 },
});
