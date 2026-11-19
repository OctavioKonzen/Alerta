import 'react-native-url-polyfill/auto';
import { Component } from 'react';
import { ScrollView, Text, TouchableOpacity, View } from 'react-native';
import { registerRootComponent } from 'expo';

// Rede de seguranca: se der erro, mostra a mensagem na tela em vez de fechar o app.
function TelaDeErro({ erro, tentar }) {
  const texto = String(erro?.stack || erro?.message || erro);
  return (
    <View style={{ flex: 1, backgroundColor: '#0f1115', padding: 24, paddingTop: 60 }}>
      <Text style={{ color: '#f2f4f8', fontSize: 22, fontWeight: '800', marginBottom: 8 }}>Ops, deu um erro</Text>
      <Text style={{ color: '#8b93a3', marginBottom: 16 }}>
        Tire um print desta tela e mande para o suporte. Depois toque em "Tentar de novo".
      </Text>
      <ScrollView style={{ flex: 1, backgroundColor: '#1a1d24', borderRadius: 12, padding: 12 }}>
        <Text style={{ color: '#ff6b6b', fontFamily: 'monospace', fontSize: 12 }} selectable>{texto}</Text>
      </ScrollView>
      {tentar ? (
        <TouchableOpacity onPress={tentar}
          style={{ backgroundColor: '#E53935', borderRadius: 10, padding: 14, alignItems: 'center', marginTop: 16 }}>
          <Text style={{ color: '#fff', fontWeight: '700', fontSize: 16 }}>Tentar de novo</Text>
        </TouchableOpacity>
      ) : null}
    </View>
  );
}

let App;
let erroAoCarregar = null;
try {
  App = require('./App').default;
} catch (e) {
  erroAoCarregar = e;
}

class Protegido extends Component {
  state = { erro: erroAoCarregar };
  static getDerivedStateFromError(erro) { return { erro }; }
  componentDidMount() {
    // Erros fora da tela (ex.: em funcoes async) tambem viram a tela de erro.
    const anterior = global.ErrorUtils?.getGlobalHandler?.();
    global.ErrorUtils?.setGlobalHandler?.((erro, fatal) => {
      if (fatal) this.setState({ erro });
      else if (anterior) anterior(erro, fatal);
    });
  }
  render() {
    if (this.state.erro) {
      return <TelaDeErro erro={this.state.erro} tentar={App ? () => this.setState({ erro: null }) : null} />;
    }
    return <App />;
  }
}

registerRootComponent(Protegido);
