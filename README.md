# Проект для портфолио #

>**Цель** - развернуть многоконтейнерное веб-приложение на одном физическом сервере с использованием Docker.

Весь трафик будет проходить через двухступенчатую систему защиты **WAF + Suricata**. Все события должны логироваться для мониторинга.

Архитектура проекта:

![примерная архитектура проекта](image/arhitecture.drawio.png)

## Преимущества этой архитектуры ##

1) Разделение ответственности
    - Каждый контейнер делает одно дело.
2) Безопасность
    - База данных спрятана за внутренней сетью, доступ только по определенному порту есть только у приложения.
    - Хранение логов в volume.
3) Мониторинг
    - Всегда можно посмотреть нагрузку на сервер.
    - Получать уведомления, если, например, сайт упал.

## Структура каталогов ##

    WAF_Suricata/
    |
    └── app/
        └── Dockerfile
        └── requirements.txt
        └── app.py
        └── templates/
            └──index.html
    |        
    └── db/
        └── init.sql
    |    
    └── loki/
        └── loki-config.yaml
    |    
    └── nginx/
        └── nginx.conf
        └── modsecurity.conf
    |    
    └── promtail/
        └── promtail-config.yaml
    
    |
    └──grafana/
        └──provisioning/
        |   └──datasources/
        |       └──loki.yaml
        |
        └── dashboards/
            └──dashboard.yaml
            └──my-dashboard.json
    |    
    └── suricata/
        └── suricata.yaml
        └── rules/
            └── local.rules

## Nginx ##

**Nginx** выполняет две ключевые роли:
1) **Reverse-proxy** - принимает запросы на порт 80 (HTTP) и перенаправляет их внутрь сети докера на контейнер с веб-приложением. Это позволяет спрятать приложение от прямого доступа извне.
2) **Web Application Firewall** - с помощью модуля ModSecurity nginx анализирует каждый запрос на наличие вредоносного кода. Если обнаруживает, то блокирует запрос, возвращая ошибку.

Для настройки надо отредактировать два файла: nginx.conf и modsecurity.conf.

Будет использоваться готовый образ **owasp/modsecurity-crs:nginx**, в котором есть сам nginx и модуль modsecurity c набором правил OWASP CRS. 

### WAF ###

WAF — это nginx с модулем ModSecurity, который стоит перед Flask-приложением и блокирует вредоносные запросы.

WAF анализирует содержимое запросов:
- Параметры URL (?id=1)
- Тело POST-запросов (формы, JSON)
- Заголовки (User-Agent, Cookie)
- Ищет паттерны атак: SQL-инъекции, XSS, командные инъекции, LFI/RFI и др.

### Взаимодействие с другими контейнерами ###

Suricata работает в режиме IDS на уровне сети (host-сеть) и не влияет на поток HTTP-запросов. Трафик идёт **параллельно**: Suricata слушает сетевой интерфейс и анализирует все пакеты, а nginx принимает HTTP-запросы и обрабатывает их на прикладном уровне. Они не общаются напрямую, но оба пишут логи в свои тома.

Nginx проксирует все прошедшие проверку запросы на контейнер app:8000 (веб-приложение). Он также может балансировать нагрузку, если у вас будет несколько экземпляров приложения, но в нашем случае — один.

Nginx пишет логи доступа и ошибок в **/var/log/nginx/**. Эти логи подмонтированы к контейнеру Promtail через общий том, и Promtail забирает их для отправки в Loki.


## App ##

С помощью ии было написано веб-приложение "Заметки". 
На этом все.

## Suricata ##

В режиме IDS мониторит сетевой трафик на сервере. Видит все попытки подключения, сканирования портов и подозрительные пакеты.

Основные компоненты конфигурации (suricata.yaml):

1) Сетевые переменные. 
    ```yaml
    vars:
    address-groups:
        HOME_NET: "[192.168.0.0/16,10.0.0.0/8,172.16.0.0/12]" # внутренняя сеть.
        EXTERNAL_NET: "!$HOME_NET" # внешняя сеть, все что не входит в home_net.
    ```
2) Правила обнаружения.
    ```yaml
    default-rule-path: /var/lib/suricata/rules
    rule-files:
      - local.rules # указываем где хранятся правила. Правила - это "сигнатуры" атак.
    ```

3) Логирование.
    ```yaml
    logging:
    outputs:
      - eve-log:
          enabled: yes
          filetype: regular
          filename: eve.json  # формат логов
          types:
            - alert
    ```

### Мониторинг ###

1) Suricata пишет все оповещения в файл eve.json внутри тома suricata-logs.
2) Контейнер promtail подключает этот же том suricata-logs и читает файл eve.json.
    - Promtail находит все *.json файлы в папке с логами, парсит их как JSON и извлекает ключевые поля (event_type, src_ip и т.д.), превращая их в удобные для поиска метки.
3) В Grafana строятся дашборды на основе этих данных.

## База данных PosgreSQL ##

1) Хранит заметки в таблице notes
2) Доступна только внутри Docker-сети webnet
3) Данные сохраняются в томе db-data

Flask-приложение обрабатывает запрос:

- Для получения данных оно подключается к PostgreSQL (контейнер db), используя переменные окружения.
- Выполняет SQL-запросы (SELECT, INSERT, DELETE).
- Формирует HTML-ответ (через шаблоны Jinja2) и отправляет его обратно через nginx пользователю.

PostgreSQL запущен только внутри сети webnet. Порт не проброшен наружу. Пароль хранится в .env (не в коде).

## Promtail, Loki, Grafana ##

Схема сбора логов:

```yaml
[Suricata]  ──┐
              │  пишут логи в файлы внутри контейнеров
[Nginx+WAF] ──┤
              │
[Flask App] ──┘
              │
              │  (общие Docker-тома)
              ▼
         [Promtail]  ──(HTTP push)──► [Loki]  ◄──(запросы)── [Grafana]
              │                               ▲
              └──────(читает файлы логов)─────┘

```

Promtail — это «сборщик логов», который читает логи из файлов, парсит их, добавляет метки и отправляет в Loki — хранилище логов. Grafana затем подключается к Loki и позволяет искать и визуализировать эти логи.

### Promtail ###

Promtail — это агент, который:
- Сканирует файлы (или принимает логи из других источников) в указанных директориях.
- Парсит содержимое, извлекает полезные поля.
- Добавляет метки (labels) — например, job="nginx", host="nginx-modsec".
- Отправляет полученные данные в Loki по HTTP API.

В вашем проекте он настроен на чтение трёх источников логов через общие тома:
```yaml
promtail:
  volumes:
    - suricata-logs:/var/log/suricata:ro
    - nginx-logs:/var/log/nginx:ro
    - app-logs:/var/log/app:ro
```

#### Конфигурация promtail-config.yaml ####

Общие настройки:
```yaml
server:
  http_listen_port: 9080 # server — порт, на котором Promtail слушает (для метрик).
  grpc_listen_port: 0

positions:
  filename: /tmp/positions.yaml # positions — файл, где хранится информация о том, до какого места прочитаны файлы (чтобы после перезапуска продолжать с того же места).

clients:
  - url: http://loki:3100/loki/api/v1/push # clients — куда отправлять логи. Здесь мы указываем Loki (контейнер с именем loki в той же сети) на порт 3100.

```
Секция **scrape_configs**:

Здесь описаны джобы (задания) по сбору логов.

Джоб 1: Suricata (логи в формате JSON)

```yaml
- job_name: suricata
  static_configs:
    - targets: [localhost]
      labels:
        job: suricata
        host: suricata
        __path__: /var/log/suricata/*.json # маска пути к файлам
  pipeline_stages:  # цепочка обработки
    - json: # пытается распарсить содержимое лога как JSON и извлечь поля (event_type, src_ip, ...).
        expressions:
          event_type: event_type
          src_ip: src_ip
          dest_ip: dest_ip
          proto: proto
          alert: alert
    - labels: # извлечённые поля превращает в метки Loki. Например, чтобы фильтровать логи по event_type (alert, http, dns и т.д.) или по протоколу.
        event_type: event_type
        proto: proto
```

Джоб 2: Nginx / ModSecurity (обычные access и error логи)

```yaml
- job_name: nginx
  static_configs:
    - targets: [localhost]
      labels:
        job: nginx
        host: nginx-modsec
        __path__: /var/log/nginx/*.log
  pipeline_stages:
    - regex:
        expression: '^(?P<remote_addr>\S+) - (?P<remote_user>\S+) \[(?P<time_local>.*?)\] "(?P<method>\S+) (?P<request_uri>\S+) (?P<http_version>\S+)" (?P<status>\d{3}) (?P<body_bytes_sent>\d+) "(?P<http_referer>.*?)" "(?P<http_user_agent>.*?)"'
    - labels:
        method: method
        status: status
```

- Здесь мы парсим стандартный access_log nginx.
- Используется регулярное выражение (regex), чтобы извлечь такие поля, как remote_addr, method, status, request_uri и др.
- Извлечённые поля method и status становятся метками, по которым можно фильтровать в Loki.

Джоб 3: Flask-приложение (логи приложения)

```yaml
- job_name: app
  static_configs:
    - targets: [localhost]
      labels:
        job: app
        host: app
        __path__: /var/log/app/*.log
  pipeline_stages:
    - regex:
        expression: '^(?P<timestamp>\S+) - (?P<level>\w+) - (?P<message>.*)$'
    - labels:
        level: level
```
- Логи приложения имеют формат: 2026-06-28 15:30:45 - INFO - Главная страница загружена.
- Регулярка извлекает timestamp, level и message.
- level становится меткой, по которой можно фильтровать (INFO, WARNING, ERROR).

### Loki ###

Loki — это горизонтально масштабируемое, высокодоступное хранилище логов, вдохновлённое Prometheus. В отличие от Elasticsearch, Loki индексирует только метки, а содержимое логов хранит в виде сжатых чанков. Это делает его очень лёгким и экономичным по ресурсам.

Конфигурация Loki (loki-config.yaml)

```yaml
auth_enabled: false # отключаем аутентификацию (Для простоты, такто так делать не надо)

server:
  http_listen_port: 3100 # порт на котором loki принимает данные от promtail и отдает их Grafana.

common: # настройка хранения
  path_prefix: /loki 
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory

schema_config: # определяет схему хранения и переодичность индексов
  configs:
    - from: 2020-10-24
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h

limits_config: # ограничение на прием логов
  allow_structured_metadata: true
  ingestion_rate_mb: 16
  ingestion_burst_size_mb: 32
```

#### Взаимодействие: Promtail → Loki ####
+ Promtail читает файлы, парсит их и формирует записи (streams) с метками и сообщением.
+ Каждая запись отправляется по HTTP на http://loki:3100/loki/api/v1/push.
+ Loki индексирует метки и сохраняет содержимое в чанки (сжатые блоки).
+ Grafana подключается к тому же адресу и выполняет запросы к Loki (через API или через встроенный плагин).

### Grafana — визуализация ###
Grafana — это веб-интерфейс, который подключается к Loki как источнику данных. Вы можете строить дашборды, используя язык запросов LogQL (аналог PromQL для логов).

docker-compose.yaml
```yaml
grafana:
  image: grafana/grafana:latest # Официальный образ Grafana из Docker Hub.
  container_name: grafana # Имя контейнера
  restart: unless-stopped # Автоматически перезапускать контейнер, если он упал (кроме случая, когда вы явно остановили его).
  environment: # Переменные окружения из .env
    - GF_SECURITY_ADMIN_USER=${GF_SECURITY_ADMIN_USER}
    - GF_SECURITY_ADMIN_PASSWORD=${GF_SECURITY_ADMIN_PASSWORD}
    - GF_INSTALL_PLUGINS=grafana-piechart-panel
  ports:
    - "3000:3000" # Проброс порта: внутри контейнера Grafana слушает 3000, наружу отдаём тот же порт.
  volumes:
    - grafana-data:/var/lib/grafana # Том для хранения данных Grafana: база данных, настройки, плагины, дашборды
    - ./grafana/provisioning:/etc/grafana/provisioning
    - ./grafana/grafana.ini:/etc/grafana/grafana.ini:ro

  depends_on: # Гарантирует, что Loki запустится до Grafana
  
    - loki
  networks: 
    - webnet # Контейнер находится в вашей внутренней сети Docker, поэтому может обращаться к другим контейнерам по имени
```
Чтобы при первом запуске grafana уже были подключены источники данных loki и готовые дашборды, необходимо создать папку **provisioning**, которую нужно смонтировать в контейнер.

Файл grafana/provisioning/datasources/loki.yaml для подключения источника данных:

```yaml
apiVersion: 1

datasources:
  - name: Loki # как будет называться источник в интерфейсе.
    type: loki #  тип данных (loki).
    access: proxy
    url: http://loki:3100 # адрес внутри Docker-сети (контейнер loki на порту 3100).
    isDefault: true
    version: 1
    editable: false # запрещаем редактирование через интерфейс (чтобы сохранить конфигурацию).
```

Файл grafana/provisioning/dashboards/dashboard.yaml:

```yaml
apiVersion: 1

providers:
  - name: 'Default'
    orgId: 1
    folder: ''
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    options:
      path: /etc/grafana/provisioning/dashboards
```
Это говорит Grafana: смотри в папку /etc/grafana/provisioning/dashboards и загружай все JSON-файлы как дашборды.

Пример (очень простой дашборд для показа логов):
**my-dashboard.json**

```json
{
  "title": "Мониторинг безопасности",
  "panels": [
    {
      "title": "Атаки WAF за последний час",
      "type": "stat",
      "targets": [
        {
          "expr": "count_over_time({job=\"nginx\", status=\"403\"}[1h])",
          "legendFormat": "Заблокировано"
        }
      ]
    },
    {
      "title": "Логи Suricata",
      "type": "logs",
      "targets": [
        {
          "expr": "{job=\"suricata\"}"
        }
      ]
    }
  ],
  "schemaVersion": 36
}
```
#### Конфигурационный файл Grafana (grafana.ini) — расширенные настройки ####

Иногда переменных окружения недостаточно. Вы можете создать свой файл grafana.ini и смонтировать его. Например, чтобы изменить таймзону, включить логирование в файл, настроить аутентификацию через OAuth.

Создайте grafana/grafana.ini:

```ini
[server]
domain = localhost
root_url = http://localhost:3000

[log]
level = info
mode = console file
file = /var/log/grafana/grafana.log

[auth.anonymous]
enabled = true
org_role = Viewer
```


Как настроить Grafana для работы с Loki:
+ Откройте Grafana: http://localhost:3000 (логин/пароль admin/admin).
+ Перейдите в Configuration → Data Sources → Add data source → выберите Loki.
+ В поле URL укажите: http://loki:3100.
+ Нажмите Save & Test.

Резюме
- Promtail — собирает логи из файлов, парсит их, добавляет метки, отправляет в Loki.
- Loki — хранилище логов, индексирует только метки, эффективно использует ресурсы.
- Grafana — визуализация и поиск по логам с помощью языка LogQL.
- Все три сервиса работают в своих контейнерах, объединены общей Docker-сетью.