# tools/generate_hashes.py
# Uso:
#   python tools/generate_hashes.py
# Ele pede as senhas de: aprendiz, companheiro e mestre e imprime os hashes.

import getpass
from streamlit_authenticator.utilities.hasher import Hasher

usuarios = ["aprendiz", "companheiro", "mestre"]
senhas = []
for u in usuarios:
    s = getpass.getpass(f"Defina a senha para '{u}': ")
    senhas.append(s)

# Para várias senhas de uma vez:
hashes = Hasher.hash_list(senhas)

# Exibe no formato "usuario: hash"
for u, h in zip(usuarios, hashes):
    print(f"{u}: {h}")
