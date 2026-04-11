import sys
import os

# Ensure backend module is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.knowledge_base import _search_public_chunks

def test_search():
    query = "解析几何中切线斜率应该怎么求"
    print(f"Testing public FAISS search with query: '{query}'")
    
    results = _search_public_chunks(query, top_k=3)
    
    if not results:
        print("No results found! Make sure that data/pro_kb/pro_kb_faiss.index and texts exist and chunks are properly generated.")
        return
        
    print("\n--- TOP RESULTS ---")
    for r in results:
        print(f"Doc ID: {r.get('doc_id')}")
        print(f"Title: {r.get('title')}")
        print(f"Score: {r.get('score')} | Vector Score: {r.get('vector_score')} | Lexical Score: {r.get('lexical_score')}")
        print(f"Snippet: {r.get('snippet')}\n")
        
if __name__ == "__main__":
    test_search()
