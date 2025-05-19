from fastapi import FastAPI, HTTPException
from neo4j import GraphDatabase
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

# NEO4J_URL = "bolt://localhost:7687"
NEO4J_URL = "neo4j+s://1688050e.databases.neo4j.io"
NEO4J_USER = "neo4j"
# NEO4J_PASSWORD = "Almas201"
NEO4J_PASSWORD = "3eaKJvXAPX_qlTk0Nm5ckM_p6iV1_JeKtWxO-8-tuK8"
AUTH = (NEO4J_USER, NEO4J_PASSWORD)

driver = GraphDatabase.driver(NEO4J_URL, auth=AUTH)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "API work!"}

@app.on_event("shutdown")
def close_driver():
    driver.close()

@app.get("/graph_data")
def get_graph_data():
    query = """
    MATCH (n)
    OPTIONAL MATCH (n)-[r]->(m)
    RETURN n, collect(r) AS relations, collect(m) AS targets
    """
    try:
        with driver.session() as session:
            result = session.run(query)
            nodes = {}
            edges = []

            def get_group(node):
                labels = list(node.labels)
                if "Класс" in labels:
                    return "class"
                elif "Подкласс" in labels:
                    return "subclass"
                elif "Термин" in labels:
                    return "term"
                elif "Перевод" in labels:
                    return "translate"
                return "unknown"

            for record in result:
                n = record["n"]
                relations = record["relations"]
                targets = record["targets"]

                # Добавляем узел n
                if n.id not in nodes:
                    nodes[n.id] = {"id": n.id, "label": n["name"], "group": get_group(n)}

                # Добавляем связи, если они есть
                for i, m in enumerate(targets):
                    if m is not None:  # m может быть None, если связей нет
                        if m.id not in nodes:
                            nodes[m.id] = {"id": m.id, "label": m["name"], "group": get_group(m)}

                        r = relations[i]
                        edges.append({"from": n.id, "to": m.id, "label": r.type})

            return {"nodes": list(nodes.values()), "edges": edges}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



class Term(BaseModel):
    name: str
    category: str


class NodeData(BaseModel):
    type: str
    ru: str
    kz: str
    en: str
    parent: Optional[str] = None  # Родительский класс


def add_node_to_neo4j(tx, node_type, ru, kz, en, parent):
    # Создание основного узла
    query = (
        "MERGE (n:" + node_type + " {name: $ru, lang: 'ru'}) "
        "RETURN n"
    )
    tx.run(query, ru=ru)

    # Создание связей с переводами
    if kz:
        tx.run(
            "MERGE (kz:Перевод {name: $kz, lang: 'kz'}) "
            "WITH kz "
            "MATCH (ru:" + node_type + " {name: $ru, lang: 'ru'}) "
            "MERGE (ru)-[:LE_KAZ]->(kz)",
            ru=ru, kz=kz
        )

    if en:
        tx.run(
            "MERGE (en:Перевод {name: $en, lang: 'en'}) "
            "WITH en "
            "MATCH (ru:" + node_type + " {name: $ru, lang: 'ru'}) "
            "MERGE (ru)-[:LE_ENG]->(en)",
            ru=ru, en=en
        )

    # Если задан родительский класс, создаем связь MT (Microthesaurus)
    if parent:
        relationship = "MT" if node_type in ["Класс", "Подкласс"] else "HAS_TERMIN"
        tx.run(
            f"MATCH (parent {{name: $parent, lang: 'ru'}}), (child:{node_type} {{name: $ru, lang: 'ru'}}) "
            f"MERGE (parent)-[:{relationship}]->(child)",
            parent=parent, ru=ru
        )



@app.post("/add_node/")
def add_node(data: NodeData):
    try:
        with driver.session() as session:
            session.write_transaction(
                add_node_to_neo4j, data.type, data.ru, data.kz, data.en, data.parent
            )
        return {"success": True, "message": "Узел успешно добавлен"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get_classes")
def get_classes():
    try:
        with driver.session() as session:
            result = session.run("MATCH (n:Класс) RETURN n.name AS name")
            classes = [record["name"] for record in result]

            if not classes:
                return {"classes": []}  # Возвращаем пустой массив вместо ошибки
            
            return {"classes": classes}

    except Exception as e:
        return {"error": str(e), "classes": []}  # Ловим любую ошибку и возвращаем пустой список


@app.get("/get_subclasses")
def get_classes():
    try:
        with driver.session() as session:
            result = session.run("MATCH (n:Подкласс) RETURN n.name AS name")
            subclasses = [record["name"] for record in result]
            if not subclasses:
                return {"subclasses": []}  # Возвращаем пустой массив вместо ошибки
            
            return {"subclasses": subclasses}

    except Exception as e:
        return {"error": str(e), "subclasses": []}  # Ловим любую ошибку и возвращаем пустой список



@app.get("/classes")
def get_classes():
    query = "MATCH (c:Класс) RETURN c.name as name"
    try:
        with driver.session() as session:
            result = session.run(query)
            classes = [record["name"] for record in result]
            return {"classes": classes}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/subclasses/{class_name}")
def get_subclasses(class_name: str):
    query = """
    MATCH (c:Класс {name: $class_name})-[:MT]->(s:Подкласс)
    RETURN s.name as name
    """
    try:
        with driver.session() as session:
            result = session.run(query, class_name=class_name)
            subclasses = [record["name"] for record in result]
            return {"subclasses": subclasses}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/terms/{subclass_name}")
def get_terms(subclass_name: str):
    query = """
    MATCH (s:Подкласс {name: $subclass_name})-[:HAS_TERMIN]->(t:Термин)
    RETURN t.name as name
    """
    try:
        with driver.session() as session:
            result = session.run(query, subclass_name=subclass_name)
            terms = [record["name"] for record in result]
            return {"terms": terms}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class RelationRequest(BaseModel):
    term1: str
    term2: str
    relation_type: str

@app.post("/create_relation")
def create_relation(relation_data: dict):
    term1 = relation_data.get("term1")
    term2 = relation_data.get("term2")
    relation_type = relation_data.get("relationType")
    
    print("Полученные данные от клиента:")
    print("Термин 1:", term1)
    print("Термин 2:", term2)
    print("Тип отношения:", relation_type)  # Посмотрим, что приходит на сервер

    if relation_type not in ["NT", "BT", "RT", "UF", "SN", "MT"]:
        return {"error": "Неверный тип отношения"}
    
    query = f"""
    MATCH (t1:Термин {{name: $term1}}), (t2:Термин {{name: $term2}})
    MERGE (t1)-[:{relation_type}]->(t2)
    MERGE (t2)-[:{relation_type}]->(t1)
    """
    try:
        with driver.session() as session:
            session.run(query, term1=term1, term2=term2)
        return {"message": "Связь успешно создана"}
    except Exception as e:
        return {"error": str(e)}





'''
index.html: 

+ обработка ошибок:
    - проверка одинаковых узлов при добавлении, если есть то выдать ошибку
    - добавить рядом поля индиктор загрузки при проверки добавлении


'''

