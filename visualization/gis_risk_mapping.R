# =============================================================
# gis_risk_mapping.R
# 6PPD-Q 위험도 GIS 시각화 프로토타입
# Week 3 - 허윤서
#
# 입력: gis_mapping_data.csv (15개 도로: 위경도, 지류, AADT, 불투수면, 위험도)
# 출력: risk_map.html (인터랙티브 leaflet 지도)
#
# 필요 패키지: leaflet, dplyr
#   install.packages(c("leaflet", "dplyr"))
# =============================================================

library(leaflet)
library(dplyr)

# -------------------------------------------------------------
# 1. 데이터 불러오기
# -------------------------------------------------------------
df <- read.csv("gis_mapping_data.csv", encoding = "UTF-8", fileEncoding = "UTF-8")

# 위험도 컬럼이 숫자형인지 확인
df$위험도 <- as.numeric(df$위험도)
df$위도   <- as.numeric(df$위도)
df$경도   <- as.numeric(df$경도)

# -------------------------------------------------------------
# 2. 위험도 -> 색상 매핑 (초록 낮음 -> 빨강 높음)
# -------------------------------------------------------------
risk_palette <- colorNumeric(
  palette = c("#2ECC71", "#F1C40F", "#E74C3C"),  # 초록 -> 노랑 -> 빨강
  domain  = df$위험도
)

# -------------------------------------------------------------
# 3. 지류별 색상 (범례용 - 마커 테두리 구분)
# -------------------------------------------------------------
tributary_colors <- c(
  "탄천"   = "#8E44AD",
  "중랑천" = "#2980B9",
  "안양천" = "#16A085",
  "홍제천" = "#D35400",
  "성내천" = "#C0392B"
)
df$지류색상 <- tributary_colors[df$지류]

# -------------------------------------------------------------
# 4. 지도 생성
# -------------------------------------------------------------
map <- leaflet(df) %>%
  addTiles() %>%
  setView(lng = 127.02, lat = 37.55, zoom = 11) %>%
  addCircleMarkers(
    lng = ~경도, lat = ~위도,
    radius = ~sqrt(위험도) * 1.8,          # 위험도 클수록 마커도 크게
    color = ~지류색상,                      # 테두리 = 지류 구분
    fillColor = ~risk_palette(위험도),      # 채우기 = 위험도 색
    fillOpacity = 0.85,
    weight = 3,
    stroke = TRUE,
    label = ~paste0(도로명, " (", 소속구, ")"),
    popup = ~paste0(
      "<b>", 도로명, "</b> (", 소속구, " · ", 지류, ")<br/>",
      "AADT: ", format(AADT, big.mark = ","), "대/일<br/>",
      "불투수면비율: ", 불투수면, "%<br/>",
      "<b>위험도: ", 위험도, "점</b>"
    )
  ) %>%
  addLegend(
    position = "bottomright",
    pal = risk_palette,
    values = ~위험도,
    title = "위험도 점수",
    opacity = 0.9
  ) %>%
  addControl(
    html = paste0(
      "<div style='background:white;padding:8px;border-radius:4px;font-size:12px;line-height:1.6;'>",
      "<b>지류 구분 (테두리 색)</b><br/>",
      paste(sapply(names(tributary_colors), function(n) {
        paste0("<span style='color:", tributary_colors[n], "'>●</span> ", n)
      }), collapse = "<br/>"),
      "</div>"
    ),
    position = "topright"
  )

# -------------------------------------------------------------
# 5. HTML로 저장
# -------------------------------------------------------------
htmlwidgets::saveWidget(map, "risk_map.html", selfcontained = TRUE)

cat("완료: risk_map.html 생성됨\n")
cat("주의: 좌표는 행정동 중심점 근사값이며, 정밀 도로 구간 좌표 아님 (방법론 한계로 명시 필요)\n")
