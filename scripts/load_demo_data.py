"""
StyleSync - Script de carga de datos demo
Crea categorías y productos en PrestaShop via API Webservice
"""
import os
import requests
import xml.etree.ElementTree as ET
from xml.dom import minidom
from dotenv import load_dotenv

# ─── Cargar Entorno ───────────────────────────────────────────
ruta_env = os.path.join(".env")
load_dotenv(dotenv_path=ruta_env)

# ─── Configuración ────────────────────────────────────────────
API_KEY   = os.environ.get("PRESTASHOP_API_KEY")
BASE_URL  = "http://localhost:8080/api"
AUTH      = (API_KEY, "")
HEADERS   = {"Content-Type": "application/xml"}

# Verificación de seguridad
if not API_KEY:
    print("ERROR: No se encontró la variable PRESTASHOP_API_KEY.")
    print("   Asegúrate de que el archivo .env exista dentro de la carpeta 'docker'.")
    exit(1)

# ─── Helpers ──────────────────────────────────────────────────

def get_blank_schema(resource):
    """Obtiene el esquema XML vacío de un recurso para saber qué campos acepta"""
    url = f"{BASE_URL}/{resource}?schema=blank"
    response = requests.get(url, auth=AUTH)
    if response.status_code == 200:
        return ET.fromstring(response.text)
    raise Exception(f"Error obteniendo schema de {resource}: {response.status_code} {response.text}")

def post_resource(resource, xml_string):
    """Crea un nuevo recurso enviando XML a la API"""
    url = f"{BASE_URL}/{resource}"
    response = requests.post(url, auth=AUTH, headers=HEADERS, data=xml_string.encode("utf-8"))
    if response.status_code == 201:
        root = ET.fromstring(response.text)
        # PrestaShop devuelve el ID dentro del elemento hijo de <prestashop>
        # Buscamos el tag <id> dentro del recurso creado
        id_element = root.find(".//id")
        if id_element is not None:
            # CDATA viene como texto del elemento
            return id_element.text.strip()
        raise Exception(f"No se encontró ID en la respuesta de {resource}")
    raise Exception(f"Error creando {resource}: {response.status_code}\n{response.text}")

def get_default_language_id():
    """Obtiene el ID del idioma por defecto de la tienda"""
    url = f"{BASE_URL}/languages"
    response = requests.get(url, auth=AUTH)
    root = ET.fromstring(response.text)
    language = root.find(".//language")
    return language.get("id") if language is not None else "1"

# ─── Crear categorías ─────────────────────────────────────────

def create_category(name, parent_id, lang_id):
    """Crea una categoría en PrestaShop"""
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<prestashop>
    <category>
        <active>1</active>
        <id_parent>{parent_id}</id_parent>
        <name>
            <language id="{lang_id}"><![CDATA[{name}]]></language>
        </name>
        <description>
            <language id="{lang_id}"><![CDATA[Categoría {name} de StyleSync]]></language>
        </description>
        <link_rewrite>
            <language id="{lang_id}"><![CDATA[{name.lower().replace(" ", "-")}]]></language>
        </link_rewrite>
    </category>
</prestashop>"""
    category_id = post_resource("categories", xml)
    print(f"  ✅ Categoría creada: {name} (ID: {category_id})")
    return category_id

# ─── Crear productos ──────────────────────────────────────────

def create_product(name, price, category_id, description, reference, lang_id):
    """Crea un producto en PrestaShop"""
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<prestashop>
    <product>
        <active>1</active>
        <id_category_default>{category_id}</id_category_default>
        <price>{price}</price>
        <reference>{reference}</reference>
        <minimal_quantity>1</minimal_quantity>
        <show_price>1</show_price>
        <available_for_order>1</available_for_order>
        <name>
            <language id="{lang_id}"><![CDATA[{name}]]></language>
        </name>
        <description>
            <language id="{lang_id}"><![CDATA[{description}]]></language>
        </description>
        <description_short>
            <language id="{lang_id}"><![CDATA[{description[:100]}]]></language>
        </description_short>
        <link_rewrite>
            <language id="{lang_id}"><![CDATA[{name.lower().replace(" ", "-")}]]></language>
        </link_rewrite>
        <meta_title>
            <language id="{lang_id}"><![CDATA[{name}]]></language>
        </meta_title>
    </product>
</prestashop>"""
    product_id = post_resource("products", xml)
    print(f"  ✅ Producto creado: {name} (ID: {product_id})")
    return product_id

# ─── Datos demo StyleSync ─────────────────────────────────────

CATEGORIAS = [
    {"name": "Camisetas",   "parent": 2},
    {"name": "Pantalones",  "parent": 2},
    {"name": "Vestidos",    "parent": 2},
    {"name": "Accesorios",  "parent": 2},
    {"name": "Calzado",     "parent": 2},
]

PRODUCTOS = [
    # Camisetas
    {
        "name":        "Camiseta Básica Blanca",
        "price":       "19.99",
        "categoria":   "Camisetas",
        "reference":   "SS-CAM-001",
        "description": "Camiseta de algodón 100% orgánico. Corte recto, cuello redondo. Disponible en tallas XS a XL."
    },
    {
        "name":        "Camiseta Rayas Marineras",
        "price":       "24.99",
        "categoria":   "Camisetas",
        "reference":   "SS-CAM-002",
        "description": "Camiseta de rayas azul marino y blanco. Tejido suave de alta calidad. Perfecta para looks casuales."
    },
    {
        "name":        "Camiseta Oversize Negra",
        "price":       "29.99",
        "categoria":   "Camisetas",
        "reference":   "SS-CAM-003",
        "description": "Camiseta oversize en negro intenso. Tejido grueso premium. Tendencia urbana para el día a día."
    },
    # Pantalones
    {
        "name":        "Pantalón Chino Beige",
        "price":       "49.99",
        "categoria":   "Pantalones",
        "reference":   "SS-PAN-001",
        "description": "Pantalón chino slim fit en color beige. Tejido con elastano para mayor comodidad. Elegante y versátil."
    },
    {
        "name":        "Jeans Skinny Azul",
        "price":       "59.99",
        "categoria":   "Pantalones",
        "reference":   "SS-PAN-002",
        "description": "Vaqueros skinny de corte moderno. Denim de calidad con ligero stretch. El básico imprescindible."
    },
    # Vestidos
    {
        "name":        "Vestido Floral Midi",
        "price":       "69.99",
        "categoria":   "Vestidos",
        "reference":   "SS-VES-001",
        "description": "Vestido midi con estampado floral. Tejido fluido, escote V, manga corta. Ideal para primavera."
    },
    {
        "name":        "Vestido Negro Clásico",
        "price":       "79.99",
        "categoria":   "Vestidos",
        "reference":   "SS-VES-002",
        "description": "El vestido negro esencial de todo armario. Corte ajustado, largo rodilla. Elegancia atemporal."
    },
    # Accesorios
    {
        "name":        "Bolso Tote Canvas",
        "price":       "34.99",
        "categoria":   "Accesorios",
        "reference":   "SS-ACC-001",
        "description": "Bolso tote de canvas resistente. Asa larga y corta. Capacidad para el día a día. Color crudo."
    },
    {
        "name":        "Cinturón Piel Marrón",
        "price":       "29.99",
        "categoria":   "Accesorios",
        "reference":   "SS-ACC-002",
        "description": "Cinturón de piel genuina color marrón. Hebilla dorada. Disponible en tallas S/M y L/XL."
    },
    # Calzado
    {
        "name":        "Zapatillas Blancas Minimal",
        "price":       "89.99",
        "categoria":   "Calzado",
        "reference":   "SS-CAL-001",
        "description": "Zapatillas blancas de diseño minimalista. Suela ligera, piel sintética premium. Unisex."
    },
    {
        "name":        "Sandalias Planas Nude",
        "price":       "44.99",
        "categoria":   "Calzado",
        "reference":   "SS-CAL-002",
        "description": "Sandalias planas en color nude. Tiras ajustables, plantilla acolchada. Comodidad todo el día."
    },
]

# ─── Main ─────────────────────────────────────────────────────

def main():
    print("\n🛍️  StyleSync — Cargando datos demo en PrestaShop\n")

    # Obtener idioma por defecto
    lang_id = get_default_language_id()
    print(f"📌 Idioma detectado: ID {lang_id}\n")

    # Crear categorías y guardar sus IDs
    print("📁 Creando categorías...")
    categoria_ids = {}
    for cat in CATEGORIAS:
        cat_id = create_category(cat["name"], cat["parent"], lang_id)
        categoria_ids[cat["name"]] = cat_id

    # Crear productos asignando la categoría correcta
    print("\n📦 Creando productos...")
    for prod in PRODUCTOS:
        cat_id = categoria_ids[prod["categoria"]]
        create_product(
            name        = prod["name"],
            price       = prod["price"],
            category_id = cat_id,
            description = prod["description"],
            reference   = prod["reference"],
            lang_id     = lang_id
        )

    print("\n✅ Datos demo cargados exitosamente.")
    print("   Abre http://localhost:8080 para ver los productos en la tienda.\n")

if __name__ == "__main__":
    main()