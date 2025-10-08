# X-Web-Scraping

Um script de web scraping e análise de conteúdo para a plataforma X (antigo Twitter), focado em monitoramento contínuo, extração detalhada de metadados e processamento inteligente de mídias como imagens (OCR) e vídeos (transcrição de áudio).

## Descrição

Este script é uma ferramenta de coleta de dados (web scraping) projetada para monitorar a plataforma X, utilizando um front-end público (`twiiit.com`) para extrair postagens com base em uma lista de palavras-chave. O projeto vai muito além da simples extração de texto, incorporando um pipeline completo de análise de mídia:

* **Reconhecimento Óptico de Caracteres (OCR):** Utiliza o Tesseract para ler e extrair texto de imagens anexadas.
* **Transcrição de Áudio:** Emprega o modelo *Whisper* da OpenAI para transcrever o conteúdo falado em vídeos.

O script foi desenvolvido com foco em resiliência e automação, incluindo mecanismos de retentativas, tratamento de erros e configuração flexível para garantir a maior taxa de sucesso possível, mesmo ao lidar com alvos protegidos por medidas anti-bot.

## Principais Funcionalidades

-   **Monitoramento Contínuo:** Opera em um ciclo infinito, realizando buscas periódicas para capturar novas postagens em tempo real.
-   **Análise de Mídia Inteligente:**
    -   Extrai texto de imagens com **Tesseract OCR**.
    -   Transcreve áudio de vídeos com **OpenAI Whisper**.
    -   **Verificação de Áudio:** Utiliza `ffprobe` para detectar se um vídeo contém áudio antes de tentar a transcrição, ignorando de forma inteligente GIFs e vídeos mudos.
-   **Extração de Dados Rica:** Coleta o texto do post, metadados de publicação (data, URL), informações do autor (username, nome de exibição, status de verificação) e métricas de engajamento (respostas, reposts, curtidas).
-   **Mecanismos Anti-Bloqueio:**
    -   Utiliza `undetected-chromedriver` para uma navegação mais discreta.
    -   Sincroniza a identidade do navegador (`User-Agent`) e os `cookies` da sessão com o downloader `yt-dlp` para parecer um usuário legítimo.
    -   **Retentativas Automáticas:** Tenta baixar mídias bloqueadas (erro 403) até 3 vezes antes de desistir.
-   **Lógica de Coleta Robusta:**
    -   **Posts com falha são ignorados:** Se o download ou a transcrição de uma mídia falhar, o post não é salvo, garantindo que o script tente coletá-lo novamente em um ciclo futuro.
-   **Privacidade (LGPD):** Pseudonimiza os nomes de usuário usando um hash SHA256 com "salt" para proteger a identidade dos autores.
-   **Configuração Flexível:**
    -   Os termos de busca são gerenciados por um arquivo externo (`lista_de_buscas.txt`).
    -   Os caminhos para as dependências (Tesseract, FFmpeg) podem ser configurados diretamente no script, sem necessidade de alterar o PATH do sistema.

## Como Funciona

O algoritmo opera em um ciclo contínuo com a seguinte lógica:

1.  **Inicialização:** O script verifica a presença do Tesseract e do FFmpeg (primeiro no PATH do sistema, depois em caminhos manuais), carrega o modelo Whisper, os termos de busca e a lista de IDs já coletados.

2.  **Início do Ciclo de Busca:** Para cada termo de busca:
    -   Uma instância do navegador Chrome é aberta via Selenium.
    -   O script navega para a página de resultados no `twiiit.com`.
    -   A identidade do navegador (`User-Agent`) e os `cookies` da sessão são salvos.

3.  **Processamento dos Posts:** Para cada post novo encontrado na página:
    -   Os dados (texto, autor, etc.) são extraídos.
    -   Se houver mídia, o script tenta baixá-la usando `yt-dlp`.
    -   **Se o download falhar, o post é pulado** para ser tentado novamente no próximo ciclo.
    -   Se o download for bem-sucedido, o script verifica a extensão do arquivo.
    -   Se for uma imagem, realiza o OCR.
    -   Se for um vídeo, primeiro verifica se há uma trilha de áudio.
        -   Se houver áudio, tenta a transcrição com Whisper. **Se a transcrição falhar, o post é pulado**.
        -   Se não houver áudio, a transcrição é ignorada.

4.  **Salvamento:** Apenas os posts processados com 100% de sucesso são salvos em um arquivo JSON e seus IDs são registrados.

5.  **Pausa:** O script aguarda o intervalo definido e inicia um novo ciclo.

## Estrutura do JSON de Saída

Os dados são salvos como uma lista de objetos JSON. Cada objeto representa um post e segue esta estrutura:

```json
[
    {
        "metadados_coleta": {
            "plataforma_postagem": "X",
            "data_coleta": "2025-09-29T19:35:10.123456Z",
            "coletado_via": "web_scraping",
            "termo_busca_utilizado": "Brasil OR \"Tecnologia da Informação\""
        },
        "dados_postagem": {
            "id_post": "1234567890123456789",
            "url": "[https://x.com/usuario_exemplo/status/1234567890123456789](https://x.com/usuario_exemplo/status/1234567890123456789)",
            "data_publicacao": "2025-09-29T18:45:00Z",
            "autor": {
                "id_usuario": null,
                "id_pseudonimizado": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
                "nome_usuario": "usuario_exemplo",
                "nome_exibicao": "Usuário de Exemplo",
                "perfil_verificado": true,
                "contagem_seguidores": null
            }
        },
        "engajamento": {
            "contagem_respostas": 15,
            "contagem_reposts": 32,
            "contagem_curtidas": 128,
            "contagem_visualizacoes": null
        },
        "conteudo": {
            "texto_principal": "Discutindo o futuro...!",
            "anexos": [
                {
                    "tipo_midia": "video",
                    "url_midia": "https://twiiit.com/usuario_exemplo/status/1234567890123456789",
                    "transcricao": "Olá a todos, no vídeo de hoje..."
                }
            ]
        }
    }
]
```

## Requisitos do Sistema

### Software
-   **Python 3.8+**
-   **Tesseract OCR**: Ferramenta para reconhecimento de texto em imagens. ([Instruções de instalação](https://github.com/tesseract-ocr/tessdoc/blob/main/Installation.md))
-   **FFmpeg**: Essencial para processamento de áudio e vídeo. ([Instruções de instalação](https://ffmpeg.org/download.html))

### Bibliotecas Python
Crie um arquivo `requirements.txt` com o conteúdo abaixo e instale com `pip install -r requirements.txt`:
```txt
undetected-chromedriver
openai-whisper
pytesseract
Pillow
requests
beautifulsoup4
langdetect
selenium
```

## Instalação e Uso

### 1. Estrutura de Arquivos
Para o correto funcionamento, a seguinte estrutura de pastas e arquivos deve ser mantida no diretório raiz:
```
/X-Web-Scraping/
├── chrome_profile/
├── Coletas/
├── coletor_x.py
├── lista_de_buscas.txt
└── ids_coletados.txt (criado automaticamente)
```

### 2. Configuração
-   **Dependências**: Instale o Tesseract, o FFmpeg e as bibliotecas Python (`pip install -r requirements.txt`).
-   **Caminhos Manuais (Opcional)**: Se o Tesseract ou o FFmpeg não estiverem no PATH do sistema, configure o caminho para a pasta de instalação diretamente no script:
    ```python
    CAMINHO_TESSERACT_PASTA = r"C:\Program Files\Tesseract-OCR"
    CAMINHO_FFMPEG_PASTA = r"C:\ffmpeg\bin"
    ```
-   **Termos de Busca**: Edite o arquivo `lista_de_buscas.txt` com os termos desejados, um por linha.

### 3. Primeira Execução ("Aquecimento")
Para contornar sistemas de verificação, um "aquecimento" único do perfil do navegador é recomendado:
1.  Certifique-se de que a pasta `chrome_profile/` esteja vazia.
2.  Execute o script. Uma janela do Chrome será aberta.
3.  Nessa janela, realize as seguintes ações manualmente:
    -   Navegue para `google.com` e faça login em uma conta Google.
    -   Acesse o site alvo da coleta (`twiiit.com`).
    -   Se um CAPTCHA ou verificação de segurança aparecer, resolva-o.
4.  Após esses passos, pode fechar o navegador. A sessão de confiança foi salva.

### 4. Execução Normal
Para todas as execuções futuras, basta iniciar o script. Ele carregará o perfil "aquecido" e deverá navegar sem interrupções.
```bash
python coletor_x.py
```
Os dados coletados serão salvos na pasta `Coletas`.

## Observações Importantes

-   **Dependência do Front-End**: O coletor depende da estrutura HTML do Nitter/Twiiit. Se este site sofrer alterações significativas ou sair do ar, o script precisará de manutenção.
-   **Recursos do Sistema**: A transcrição de vídeo com o Whisper é uma tarefa intensiva e pode consumir bastante CPU.

## Licença

Este projeto é distribuído sob a licença MIT. Veja o arquivo `LICENSE` para mais detalhes.
