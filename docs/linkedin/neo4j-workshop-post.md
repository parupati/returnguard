# LinkedIn post: AI Workshop with Neo4j and Microsoft (AICamp, Chicago, October 1, 2026)

Event: https://www.aicamp.ai/event/eventdetails/W2026100111
Lab: https://github.com/neo4j-partners/hands-on-lab-neo4j-and-microsoft

---

Spent an afternoon at the **AI Workshop with Neo4j and Microsoft**, hosted by AICamp at Microsoft's Chicago office,
building an AI agent on top of a knowledge graph in about three hours.

The lab, start to finish:

1. **Getting started:** deployed **Neo4j Aura Professional on Azure**
2. **Moving data:** loaded SEC EDGAR quarterly filings from asset managers with more than $100M under management,
   using **LOAD CSV** and the **Aura Importer**, then explored the ownership network visually in **Neo4j Bloom**
3. **AI and agents:** extracted content from filings with **Azure Document Intelligence**, connected
   **Microsoft Foundry** to Neo4j, and built an agent that answers plain-English questions by reasoning over the
   graph

**My take:** the AI world is moving fast, and traditional RAG is no longer enough on its own. Finding text that
*looks* similar to a question isn't the same as understanding how things are *connected*. To decode the
relationships between many data points, we need to combine vector search with knowledge graphs (**GraphRAG**).
That's what lets an agent follow the links, from asset managers to their holdings to the companies they hold, and
return answers that are more accurate and easier to explain, because you can see the path it took.

It also got me thinking about my recent hackathon agent, ReturnGuard. Customers, products, orders and returns are a
natural graph too.

Thanks to **Ben Lackey**, **Nikki Conley** and **Chris Mitchell** for a great session, and to **AICamp** for
organizing. The lab is open source if you'd like to try it:
github.com/neo4j-partners/hands-on-lab-neo4j-and-microsoft

#Neo4j #KnowledgeGraphs #GraphRAG #AIAgents #MicrosoftFoundry #Azure #AICamp #Chicago

---

## Short version

Hands-on afternoon at the **AI Workshop with Neo4j and Microsoft** (AICamp, Chicago): deployed **Neo4j Aura on
Azure**, loaded SEC EDGAR asset-manager filings into a knowledge graph, explored it in **Neo4j Bloom**, and built a
**Microsoft Foundry** agent that answers ownership questions by following graph relationships. AI is moving fast,
and traditional RAG alone no longer cuts it: to decode the relationships between many data points and get the most
accurate answers, we need vector search *and* knowledge graphs working together, which is GraphRAG. Thanks Ben
Lackey, Nikki Conley and Chris Mitchell! Lab: github.com/neo4j-partners/hands-on-lab-neo4j-and-microsoft

#Neo4j #GraphRAG #AIAgents #KnowledgeGraphs
