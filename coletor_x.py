# -*- coding: utf-8 -*-
"""
Script de web scraping e análise de conteúdo projetado para monitorar a rede social X (antigo Twitter)
através de um front-end web (Nitter/Twiiit), coletando postagens com base em uma
lista de termos de busca.

Seu principal diferencial é a capacidade de também processar as mídias anexadas as postagens:
- Utiliza Tesseract OCR para extrair texto de imagens.
- Utiliza o modelo Whisper da OpenAI para transcrever o áudio de vídeos.
"""
import time
import json
import hashlib
import re
import os
import subprocess
import sys
import platform
import traceback
from datetime import datetime
from typing import Set, Dict, Any, List, Optional, Tuple
from pathlib import Path

import undetected_chromedriver as uc
import whisper
import pytesseract
from PIL import Image
import requests
from bs4 import BeautifulSoup
from langdetect import detect_langs, DetectorFactory
from langdetect.lang_detect_exception import LangDetectException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

DetectorFactory.seed = 0

# --- CONFIGURAÇÃO DE AMBIENTE E CONSTANTES ---
SCRIPT_DIR = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
BIN_DIR = SCRIPT_DIR / "bin"
if BIN_DIR.is_dir():
    os.environ["PATH"] = str(BIN_DIR) + os.pathsep + os.environ["PATH"]

# Se Tesseract ou FFmpeg não estiverem no PATH do sistema, preencha a pasta onde o executável está.
# Deixe a string vazia (ex: "") se o programa já estiver no PATH.
CAMINHO_TESSERACT_PASTA = r"C:\Program Files\Tesseract-OCR"
CAMINHO_FFMPEG_PASTA = r"C:\ffmpeg\bin"

# Verificação e configuração do Tesseract OCR
tesseract_configurado = False
try:
    # 1. Tenta encontrar no PATH do sistema primeiro
    creation_flags = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
    subprocess.run(['tesseract', '--version'], check=True, capture_output=True, creationflags=creation_flags)
    print("[INFO] Tesseract OCR encontrado no PATH do sistema.")
    tesseract_configurado = True
except (subprocess.CalledProcessError, FileNotFoundError):
    print("[ALERTA] Tesseract OCR não encontrado no PATH. Tentando caminho manual...")
    # 2. Se falhar, tenta o caminho manual
    if CAMINHO_TESSERACT_PASTA and Path(CAMINHO_TESSERACT_PASTA).is_dir():
        caminho_exe = Path(CAMINHO_TESSERACT_PASTA) / "tesseract.exe"
        if caminho_exe.is_file():
            pytesseract.pytesseract.tesseract_cmd = str(caminho_exe)
            print(f"[INFO] Tesseract OCR configurado com sucesso pelo caminho manual: {caminho_exe}")
            tesseract_configurado = True

if not tesseract_configurado:
    print("[ERRO FATAL] Tesseract OCR não foi encontrado no PATH nem no caminho manual especificado.")
    sys.exit(1)

# Verificação e configuração do FFmpeg
ffmpeg_configurado = False
try:
    # 1. Tenta encontrar no PATH do sistema primeiro
    creation_flags = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
    subprocess.run(['ffmpeg', '-version'], check=True, capture_output=True, creationflags=creation_flags)
    print("[INFO] FFmpeg encontrado no PATH do sistema.")
    ffmpeg_configurado = True
except (subprocess.CalledProcessError, FileNotFoundError):
    print("[ALERTA] FFmpeg não encontrado no PATH. Tentando caminho manual...")
    # 2. Se falhar, tenta adicionar a pasta manual ao PATH
    if CAMINHO_FFMPEG_PASTA and Path(CAMINHO_FFMPEG_PASTA).is_dir():
        os.environ["PATH"] = str(CAMINHO_FFMPEG_PASTA) + os.pathsep + os.environ["PATH"]
        # 3. Re-verifica para confirmar que agora funciona
        try:
            subprocess.run(['ffmpeg', '-version'], check=True, capture_output=True, creationflags=creation_flags)
            print(f"[INFO] FFmpeg configurado com sucesso pelo caminho manual: {CAMINHO_FFMPEG_PASTA}")
            ffmpeg_configurado = True
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass # A tentativa manual também falhou

if not ffmpeg_configurado:
    print("[ERRO FATAL] FFmpeg não foi encontrado no PATH nem no caminho manual especificado.")
    sys.exit(1)

# --- Constantes do Coletor ---
INSTANCIA = "https://twiiit.com"
SALT_LGPD = "dAurora_Salt"
MAX_RESULTADOS_POR_BUSCA = 20
INTERVALO_COLETA_SEGUNDOS = 60
PASTA_DOWNLOADS = SCRIPT_DIR / "midia_coletada"
PASTA_SAIDA = SCRIPT_DIR / "Coletas"
DELETAR_MIDIA_APOS_COLETA = True
TEMPO_ESPERA_SELENIUM = 60
ARQUIVO_IDS_PERSISTIDOS = SCRIPT_DIR / "ids_coletados.txt"
PROFILE_PATH = SCRIPT_DIR / "chrome_profile"
COOKIES_PATH = SCRIPT_DIR / "cookies.txt"

try:
    NOME_ARQUIVO_BUSCAS = "lista_de_buscas.txt"
    with open(SCRIPT_DIR / NOME_ARQUIVO_BUSCAS, 'r', encoding='utf-8') as f:
        LISTA_DE_BUSCAS = [linha.strip() for linha in f if linha.strip() and not linha.startswith('#')]
    if not LISTA_DE_BUSCAS:
        print(f"[ALERTA] Arquivo de buscas '{NOME_ARQUIVO_BUSCAS}' está vazio.")
        sys.exit(1)
    print(f"[INFO] {len(LISTA_DE_BUSCAS)} termos de busca carregados de '{NOME_ARQUIVO_BUSCAS}'.")
except FileNotFoundError:
    print(f"\n[ERRO FATAL] Arquivo de buscas '{NOME_ARQUIVO_BUSCAS}' não foi encontrado.")
    sys.exit(1)

SELECTORS_POST_CONTAINER = ['div.tweet-card', 'div.timeline-item']

# --- Funções Auxiliares ---
def carregar_ids_ja_coletados(caminho_arquivo: Path) -> Set[str]:
    if not caminho_arquivo.exists(): return set()
    try:
        with open(caminho_arquivo, 'r', encoding='utf-8') as f:
            return {line.strip() for line in f if line.strip()}
    except Exception as e:
        print(f"[ALERTA] Não foi possível ler o arquivo de IDs '{caminho_arquivo}': {e}")
        return set()

def salvar_novos_ids(caminho_arquivo: Path, novos_ids: List[str]):
    try:
        with open(caminho_arquivo, 'a', encoding='utf-8') as f:
            for post_id in novos_ids: f.write(f"{post_id}\n")
    except Exception as e:
        print(f"[ALERTA] Não foi possível salvar os novos IDs no arquivo '{caminho_arquivo}': {e}")

def pseudonimizar_usuario(username: str) -> str:
    return hashlib.sha256(f"{username}{SALT_LGPD}".encode('utf-8')).hexdigest()

def parse_stat_value(text: str) -> int:
    text = text.strip().lower()
    if not text: return 0
    text_limpo = re.sub(r'[^\d.km]', '', text)
    multiplicador = 1
    if 'k' in text_limpo: multiplicador = 1000; text_limpo = text_limpo.replace('k', '')
    elif 'm' in text_limpo: multiplicador = 1_000_000; text_limpo = text_limpo.replace('m', '')
    try: return int(float(text_limpo) * multiplicador)
    except (ValueError, TypeError): return 0

def converter_data_para_iso(data_texto: str) -> Optional[str]:
    if not data_texto: return None
    try:
        data_limpa = data_texto.replace('· ', '').replace(' UTC', '').strip()
        meses = {'Jan':'01','Feb':'02','Mar':'03','Apr':'04','May':'05','Jun':'06','Jul':'07','Aug':'08','Sep':'09','Oct':'10','Nov':'11','Dec':'12'}
        partes = data_limpa.replace(',', '').split()
        mes_num, dia, ano, hora_min, am_pm = meses[partes[0]], partes[1].zfill(2), partes[2], partes[3], partes[4]
        hora, minuto = map(int, hora_min.split(':'))
        if am_pm == 'PM' and hora != 12: hora += 12
        if am_pm == 'AM' and hora == 12: hora = 0
        data_obj = datetime(int(ano), int(mes_num), int(dia), hora, minuto)
        return data_obj.strftime('%Y-%m-%dT%H:%M:%SZ')
    except Exception: return data_texto

def verificar_idioma_portugues(texto: str) -> bool:
    try:
        deteccoes = detect_langs(texto)
        if deteccoes and deteccoes[0].lang == 'pt' and deteccoes[0].prob > 0.95: return True
        return False
    except LangDetectException: return False

def salvar_cookies_para_yt_dlp(driver: uc.Chrome, caminho_arquivo: Path):
    with open(caminho_arquivo, 'w', encoding='utf-8') as f:
        f.write("# Netscape HTTP Cookie File\n")
        cookies = driver.get_cookies()
        for cookie in cookies:
            f.write(
                f"{cookie.get('domain', '')}\tTRUE\t{cookie.get('path', '/')}\t"
                f"{str(cookie.get('secure', 'FALSE')).upper()}\t{int(cookie.get('expiry', 0))}\t"
                f"{cookie.get('name', '')}\t{cookie.get('value', '')}\n"
            )

# --- FUNÇÕES DE MÍDIA ---
def download_midia(url: str, pasta_destino: Path, post_id: str, caminho_cookies: Path, user_agent: str) -> Tuple[bool, Optional[Path]]:
    arquivos_existentes = list(pasta_destino.glob(f"{post_id}.*"))
    if arquivos_existentes:
        print(f"  - Mídia já existente: {arquivos_existentes[0].name}")
        return True, arquivos_existentes[0]

    caminho_saida_template = pasta_destino / f'{post_id}.%(ext)s'
    
    cmd = [
        'yt-dlp', '--cookies', str(caminho_cookies), '--user-agent', user_agent,
        '--no-warnings', '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        '--merge-output-format', 'mp4', '-o', str(caminho_saida_template),
        '--restrict-filenames', url
    ]
    flags = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0

    for tentativa in range(1, 4):
        try:
            print(f"  - Baixando mídia (ID: {post_id}, Tentativa: {tentativa})...", end="\r")
            subprocess.run(cmd, capture_output=True, check=True, creationflags=flags, timeout=120)
            
            arquivos_baixados = list(pasta_destino.glob(f"{post_id}.*"))
            if arquivos_baixados:
                print(f"  - Mídia salva: {arquivos_baixados[0].name}")
                return True, arquivos_baixados[0]
            
            return False, None
            
        except subprocess.CalledProcessError as e:
            erro_yt_dlp = e.stderr.decode('utf-8', errors='ignore').strip().lower()
            if '403' in erro_yt_dlp or 'forbidden' in erro_yt_dlp:
                if tentativa < 3:
                    print(f"  - [ALERTA] Download bloqueado (403) para ID {post_id}. Tentando novamente em 5s...")
                    time.sleep(5)
                    continue
            else:
                print(f"  - [ERRO] Falha no download (yt-dlp) para o post ID: {post_id}")
                return False, None
        except Exception:
            print(f"  - [ERRO] Erro inesperado no download do post ID: {post_id}.")
            return False, None

    print(f"  - [ERRO] Download do post ID {post_id} falhou após 3 tentativas.")
    return False, None

def transcrever_imagem_ocr(caminho_imagem: Path) -> Optional[str]:
    try:
        print(f"  - Lendo texto da imagem (OCR): {caminho_imagem.name}", end="\r")
        texto = pytesseract.image_to_string(Image.open(caminho_imagem), lang='por+eng')
        return texto.strip() if texto else None
    except Exception:
        print(f"  - [ALERTA] Falha no OCR da imagem: {caminho_imagem.name}")
        return None

def transcrever_video(caminho_video: Path, modelo_whisper) -> Tuple[bool, Optional[str]]:
    try:
        print(f"  - Transcrevendo vídeo: {caminho_video.name}", end="\r")
        resultado = modelo_whisper.transcribe(str(caminho_video), fp16=False, language='pt')
        return True, resultado.get("text", "").strip()
    except Exception as e:
        print(f"\n  - [ERRO TRANSCRIÇÃO] Falha em '{caminho_video.name}'. Verifique o FFmpeg. Erro: {e}\n")
        return False, None

def midia_tem_audio(caminho_midia: Path) -> bool:
    if not caminho_midia.exists(): return False
    cmd = [
        'ffprobe', '-v', 'error', '-select_streams', 'a:0',
        '-show_entries', 'stream=codec_type',
        '-of', 'default=noprint_wrappers=1:nokey=1', str(caminho_midia)
    ]
    flags = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
    try:
        resultado = subprocess.run(cmd, capture_output=True, text=True, check=True, creationflags=flags)
        return bool(resultado.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

# --- FUNÇÕES DE COLETA ---
def iniciar_driver() -> uc.Chrome:
    options = uc.ChromeOptions()
    options.add_argument(f"--user-data-dir={PROFILE_PATH}")
    driver = uc.Chrome(options=options, headless=False)
    return driver

def coletar_posts_com_selenium(posts_ja_coletados: Set[str], modelo_whisper) -> List[Dict[str, Any]]:
    novos_posts_neste_ciclo = []
    PASTA_DOWNLOADS.mkdir(exist_ok=True)
    driver = iniciar_driver()
    wait = WebDriverWait(driver, TEMPO_ESPERA_SELENIUM)
    
    try:
        for termo_busca in LISTA_DE_BUSCAS:
            print(f"\nBuscando por: '{termo_busca}'")
            try:
                search_url = f"{INSTANCIA}/search?f=tweets&q={termo_busca}&lang=pt"
                driver.get(search_url)
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ", ".join(SELECTORS_POST_CONTAINER))))
                
                user_agent = driver.execute_script("return navigator.userAgent;")
                salvar_cookies_para_yt_dlp(driver, COOKIES_PATH)
                
                soup = BeautifulSoup(driver.page_source, 'html.parser')
                post_items = soup.select(", ".join(SELECTORS_POST_CONTAINER))

                for item in post_items[:MAX_RESULTADOS_POR_BUSCA]:
                    post_path_element = item.select_one('a[href*="/status/"]')
                    post_path = post_path_element['href'] if post_path_element else ""
                    if '#' in post_path: post_path = post_path.split('#')[0]

                    post_id = post_path.split('/status/')[-1] if "/status/" in post_path else None
                    if not post_id or post_id in posts_ja_coletados: continue
                    
                    texto = item.select_one('div.tweet-content').text.strip() if item.select_one('div.tweet-content') else ""
                    if not texto or not verificar_idioma_portugues(texto): continue

                    username = item.select_one('a.username').text.strip('@') if item.select_one('a.username') else None
                    if not username: continue

                    data_publicacao_str = item.select_one('.tweet-date a')['title'] if item.select_one('.tweet-date a') else ''
                    nome_completo_str = item.select_one('a.fullname').text.strip() if item.select_one('a.fullname') else ''
                    verificado_bool = bool(item.select_one('.icon-verified'))
                    
                    stats_container = item.select_one('.tweet-stats')
                    respostas_int = parse_stat_value(stats_container.select_one('.icon-comment').parent.text) if stats_container and stats_container.select_one('.icon-comment') else 0
                    retweets_int = parse_stat_value(stats_container.select_one('.icon-retweet').parent.text) if stats_container and stats_container.select_one('.icon-retweet') else 0
                    likes_int = parse_stat_value(stats_container.select_one('.icon-heart').parent.text) if stats_container and stats_container.select_one('.icon-heart') else 0
                    
                    anexos_list = []
                    url_para_download, tipo_midia_detectado = None, None
                    
                    video_tag = item.select_one('div.attachments .attachment.video-container')
                    imagem_tag = item.select_one('div.attachments .attachment.image img')

                    if video_tag:
                        url_para_download, tipo_midia_detectado = f"{INSTANCIA}{post_path}", "video"
                    elif imagem_tag and imagem_tag.get('src'):
                        url_para_download = imagem_tag['src']
                        if url_para_download.startswith('/'): url_para_download = INSTANCIA + url_para_download
                        tipo_midia_detectado = "imagem"

                    if url_para_download:
                        sucesso_download, caminho_midia = download_midia(url_para_download, PASTA_DOWNLOADS, post_id, COOKIES_PATH, user_agent)

                        # --- LÓGICA PRINCIPAL DA COLETA ---
                        if not sucesso_download:
                            print(f"  - [INFO] Falha no download da mídia do post ID {post_id}. Será ignorado para nova tentativa no próximo ciclo.")
                            continue

                        transcricao = None
                        if caminho_midia:
                            extensao = caminho_midia.suffix.lower()
                            if extensao in ['.jpg', '.jpeg', '.png', '.webp']:
                                transcricao = transcrever_imagem_ocr(caminho_midia)
                            
                            elif extensao in ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.unknown_video', '.m3u8']:
                                if midia_tem_audio(caminho_midia):
                                    sucesso_transcricao, texto_transcrito = transcrever_video(caminho_midia, modelo_whisper)
                                    if not sucesso_transcricao:
                                        print(f"  - [INFO] Falha na transcrição do post ID {post_id}. Será ignorado para nova tentativa no próximo ciclo.")
                                        if DELETAR_MIDIA_APOS_COLETA and caminho_midia.exists():
                                            os.remove(caminho_midia)
                                        continue
                                    transcricao = texto_transcrito
                                else:
                                    print(f"  - [INFO] Mídia {caminho_midia.name} é um vídeo sem áudio. Transcrição ignorada.")
                            
                            if DELETAR_MIDIA_APOS_COLETA and caminho_midia.exists():
                                os.remove(caminho_midia)
                        
                        anexos_list.append({
                            "tipo_midia": tipo_midia_detectado, "url_midia": url_para_download,
                            "transcricao": transcricao
                        })

                    post_final = {
                        "metadados_coleta": {"plataforma_postagem":"X", "data_coleta":datetime.now().isoformat()+"Z", "coletado_via":"web_scraping", "termo_busca_utilizado":termo_busca},
                        "dados_postagem": {"id_post":post_id, "url":f"https://x.com/{username}/status/{post_id}", "data_publicacao":converter_data_para_iso(data_publicacao_str), "autor":{"id_usuario":None, "id_pseudonimizado":pseudonimizar_usuario(username), "nome_usuario":username, "nome_exibicao":nome_completo_str, "perfil_verificado":verificado_bool, "contagem_seguidores":None}},
                        "engajamento": {"contagem_respostas":respostas_int, "contagem_reposts":retweets_int, "contagem_curtidas":likes_int, "contagem_visualizacoes":None},
                        "conteudo": {"texto_principal":texto, "anexos":anexos_list}
                    }
                    
                    novos_posts_neste_ciclo.append(post_final)
                    posts_ja_coletados.add(post_id)
                    print(f"  - Novo post processado! (ID: {post_id})")

            except TimeoutException: print(f"  - [ERRO] Tempo esgotado ao buscar por '{termo_busca}'.")
            except Exception: print(f"  - [ERRO] Erro inesperado na busca por '{termo_busca}'.")
    finally:
        if driver: driver.quit()
        if COOKIES_PATH.exists(): os.remove(COOKIES_PATH)
            
    return novos_posts_neste_ciclo

# --- BLOCO DE EXECUÇÃO PRINCIPAL ---
if __name__ == "__main__":
    print("\n" + "="*60)
    print("      INICIANDO COLETOR DE DADOS (X)")
    print("="*60 + "\n")
    try:
        ids_coletados_global = carregar_ids_ja_coletados(ARQUIVO_IDS_PERSISTIDOS)
        print(f"[INFO] {len(ids_coletados_global)} IDs de posts já coletados foram carregados.")
        
        print("\nCarregando modelo de transcrição Whisper (base)... Isso pode levar um momento.")
        modelo_whisper = whisper.load_model("base")
        print("Modelo carregado com sucesso!\n")
        
        PASTA_SAIDA.mkdir(exist_ok=True)
        
        while True:
            timestamp_inicio_ciclo = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n--- INICIANDO NOVO CICLO DE COLETA ({timestamp_inicio_ciclo}) ---")
            novos_posts = coletar_posts_com_selenium(ids_coletados_global, modelo_whisper)
            if novos_posts:
                print(f"\nSUCESSO! {len(novos_posts)} novo(s) post(s) coletado(s) neste ciclo.")
                timestamp_salvamento = datetime.now().strftime("%Y%m%d_%H%M%S")
                nome_arquivo_base = f"Coleta_{timestamp_salvamento}.json"
                caminho_arquivo_final = PASTA_SAIDA / nome_arquivo_base
                with open(caminho_arquivo_final, 'w', encoding='utf-8') as f:
                    json.dump(novos_posts, f, ensure_ascii=False, indent=4)
                print(f"Dados salvos em: {caminho_arquivo_final}")
                ids_deste_ciclo = [post["dados_postagem"]["id_post"] for post in novos_posts]
                salvar_novos_ids(ARQUIVO_IDS_PERSISTIDOS, ids_deste_ciclo)
                print(f"{len(ids_deste_ciclo)} novo(s) ID(s) foram adicionados ao arquivo de persistência.")
            else:
                print("\nNenhum post novo encontrado neste ciclo.")
            print(f"--- Ciclo concluído. Aguardando {INTERVALO_COLETA_SEGUNDOS} segundos... ---")
            time.sleep(INTERVALO_COLETA_SEGUNDOS)
    except KeyboardInterrupt:
        print("\n\nColeta interrompida pelo usuário.")
    except WebDriverException as e:
        print(f"\n[ERRO FATAL DE WEBDRIVER] Verifique sua instalação do Chrome/ChromeDriver: {e}")
    except Exception as e:
        print(f"\n[ERRO FATAL] Ocorreu um erro inesperado: {e}")

    print("Monitoramento concluído.")

